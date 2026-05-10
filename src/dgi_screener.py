"""DGI Stock Screener — daily programmatic screening of S&P 500 for
dividend growth investing opportunities with technical timing.

100% programmatic (no LLM). Uses yfinance for data, custom metrics for scoring.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_symbols(symbols_str: str) -> list[str]:
    """Parse ticker symbols from comma-separated config string."""
    if not symbols_str:
        logger.warning("No symbols configured for DGI screener")
        return []
    symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    logger.info("Loaded %d symbols from config", len(symbols))
    return symbols


async def run_dgi_screener(config, cosmos) -> dict:
    """Run the full DGI screening pipeline.

    Steps:
    1. Load symbols from config (comma-separated)
    2. Fetch yfinance data for each symbol
    3. Calculate fundamental + technical metrics
    4. Apply minimum filters
    5. Calculate quality scores
    6. Select Top N by score
    7. Categorize each stock
    8. Update days_on_list persistence
    9. Write to CosmosDB
    10. Write daily snapshot

    Returns:
        Summary dict with screening stats.
    """
    from .yfinance_fetcher import YFinanceFetcher
    from . import dgi_metrics

    dgi_config = config.config.get("dgi_screener", {})
    symbols_str = dgi_config.get("symbols", "")
    top_n = dgi_config.get("top_n", 20)
    filters = dgi_config.get("filters", {})
    tech_config = dgi_config.get("technical_indicators", {})
    weights = dgi_config.get("score_weights", {})

    now = datetime.now(timezone.utc)
    run_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Load symbols from config
    symbols = _load_symbols(symbols_str)
    if not symbols:
        logger.error("No symbols loaded — aborting DGI screener run")
        return {"error": "No symbols loaded", "total_screened": 0}

    total_screened = len(symbols)
    logger.info("DGI Screener: starting with %d symbols", total_screened)

    # 2. Fetch yfinance data
    logger.info("DGI Screener: fetching yfinance data for %d symbols...", total_screened)
    fetcher = YFinanceFetcher()
    batch_data = fetcher.get_batch_data(symbols)
    logger.info("DGI Screener: fetched data for %d / %d symbols", len(batch_data), total_screened)
    if not batch_data:
        logger.error("DGI Screener: no data returned from yfinance — aborting")
        return {"error": "No data from yfinance", "total_screened": total_screened}

    # 3-4. Calculate metrics and apply filters
    candidates = []
    filtered_out = 0
    errors = 0
    for idx, (symbol, item) in enumerate(batch_data.items()):
        if not symbol:
            continue

        try:
            info = item.get("info", {})
            dividends = item.get("dividends")
            history = item.get("history")

            logger.info("[DGI %d/%d] %s — info keys: %d, dividends: %s, history: %s",
                        idx + 1, len(batch_data), symbol,
                        len(info) if info else 0,
                        f"{len(dividends)} entries" if dividends is not None and hasattr(dividends, '__len__') else str(type(dividends)),
                        f"{len(history)} rows" if history is not None and hasattr(history, '__len__') else str(type(history)))

            years = dgi_metrics.calculate_years_consecutive_increases(dividends)
            cagr = dgi_metrics.calculate_dividend_cagr(dividends)

            metrics = {
                "dividend_yield": info.get("dividendYield") or 0,
                "dividend_cagr_5y": cagr,
                "years_consecutive_increases": years,
                "payout_ratio": info.get("payoutRatio") or 0,
                "pe_ratio": info.get("trailingPE") or 0,
                "forward_pe": info.get("forwardPE") or 0,
                "debt_to_equity": (info.get("debtToEquity") or 0) / 100
                if info.get("debtToEquity") and info["debtToEquity"] > 10
                else (info.get("debtToEquity") or 0),
                "roe": info.get("returnOnEquity") or 0,
                "market_cap": info.get("marketCap") or 0,
                "current_price": info.get("currentPrice")
                or info.get("regularMarketPrice")
                or 0,
                "sector": info.get("sector", ""),
                "exchange": info.get("exchange", ""),
            }

            logger.info("[DGI %s] yield=%.3f, cagr=%.3f, years=%d, payout=%.2f, pe=%.1f, de=%.2f, mcap=%s",
                        symbol, metrics["dividend_yield"], cagr, years,
                        metrics["payout_ratio"], metrics["pe_ratio"],
                        metrics["debt_to_equity"],
                        f"{metrics['market_cap']/1e9:.1f}B" if metrics["market_cap"] else "0")

            if not dgi_metrics.passes_minimum_filters(metrics, filters):
                logger.info("[DGI %s] FILTERED OUT — failed minimum filters", symbol)
                filtered_out += 1
                continue

            # Technical timing
            if history is None or (hasattr(history, 'empty') and history.empty):
                logger.warning("[DGI %s] No price history — skipping technical score", symbol)
                continue

            tech_kwargs = {}
            if "rsi_period" in tech_config:
                tech_kwargs["rsi_period"] = tech_config["rsi_period"]
            if "bb_period" in tech_config:
                tech_kwargs["bb_period"] = tech_config["bb_period"]
            if "bb_std" in tech_config:
                tech_kwargs["bb_std"] = tech_config["bb_std"]
            tech_score = dgi_metrics.calculate_technical_timing_score(
                history["Close"].values,
                history["High"].values,
                history["Low"].values,
                metrics.get("current_price", 0),
                **tech_kwargs,
            )

            technicals = tech_score if isinstance(tech_score, dict) else {
                "technical_timing_score": tech_score
            }

            quality = dgi_metrics.calculate_quality_score(
                metrics, technicals
            )

            logger.info("[DGI %s] PASSED — quality_score=%.2f, tech_timing=%s, category pending",
                        symbol, quality,
                        technicals.get("score", technicals.get("technical_timing_score", "?")))

            candidates.append({
                "symbol": symbol,
                "metrics": metrics,
                "technicals": technicals,
                "quality_score": round(quality, 2),
            })

        except Exception as e:
            logger.warning("[DGI %s] ERROR: %s", symbol, e, exc_info=True)
            errors += 1
            continue

    passed_filters = len(candidates)
    logger.info("DGI Screener: %d passed, %d filtered out, %d errors, out of %d fetched",
                passed_filters, filtered_out, errors, len(batch_data))

    # 5-6. Sort by score and take top N
    candidates.sort(key=lambda x: x["quality_score"], reverse=True)
    top_entries = candidates[:top_n]

    # 7. Categorize each
    for i, entry in enumerate(top_entries):
        entry["rank"] = i + 1
        entry["category"] = dgi_metrics.categorize_stock(entry["metrics"])

    # 8. Update days_on_list
    previous_top20 = {}
    try:
        prev_docs = cosmos.get_dgi_top20()
        for doc in prev_docs:
            sym = doc.get("symbol", "")
            if sym:
                previous_top20[sym] = doc
    except Exception as e:
        logger.warning("Could not load previous top 20: %s", e)

    new_symbols = []
    dropped_symbols = []
    current_symbols = {e["symbol"] for e in top_entries}
    prev_symbols = set(previous_top20.keys())

    for entry in top_entries:
        sym = entry["symbol"]
        if sym in previous_top20:
            prev = previous_top20[sym]
            entry["days_on_list"] = prev.get("days_on_list", 0) + 1
            entry["first_appeared"] = prev.get("first_appeared", run_date)
        else:
            entry["days_on_list"] = 1
            entry["first_appeared"] = run_date
            new_symbols.append(sym)

    dropped_symbols = list(prev_symbols - current_symbols)

    # 9. Write to CosmosDB
    docs_to_upsert = []
    for entry in top_entries:
        tech_timing_score = (
            entry["technicals"].get("score", 0)
            if isinstance(entry["technicals"], dict)
            else 0
        )
        doc = {
            "id": f"top20_{entry['symbol']}",
            "symbol": entry["symbol"],
            "doc_type": "dgi_top20",
            "rank": entry["rank"],
            "quality_score": entry["quality_score"],
            "category": entry["category"],
            "days_on_list": entry["days_on_list"],
            "first_appeared": entry["first_appeared"],
            "last_updated": run_date,
            "metrics": entry["metrics"],
            "technicals": entry["technicals"],
            "sector": entry["metrics"].get("sector", ""),
            "exchange": entry["metrics"].get("exchange", ""),
        }
        docs_to_upsert.append(doc)

    try:
        cosmos.upsert_dgi_top20(docs_to_upsert)
        if dropped_symbols:
            cosmos.delete_dgi_dropped(dropped_symbols)
        logger.info("DGI Screener: wrote %d entries, dropped %d",
                     len(docs_to_upsert), len(dropped_symbols))
    except Exception as e:
        logger.error("Failed to write DGI results to CosmosDB: %s", e)

    # 10. Write daily snapshot
    avg_days = (
        sum(e["days_on_list"] for e in top_entries) / len(top_entries)
        if top_entries
        else 0
    )
    snapshot = {
        "id": f"snapshot_{now.strftime('%Y%m%d')}",
        "symbol": "__GLOBAL__",
        "doc_type": "daily_snapshot",
        "day": now.strftime("%Y-%m-%d"),
        "run_date": run_date,
        "top_20": [
            {
                "symbol": e["symbol"],
                "rank": e["rank"],
                "score": e["quality_score"],
                "category": e["category"],
                "days_on_list": e["days_on_list"],
            }
            for e in top_entries
        ],
        "stats": {
            "total_screened": total_screened,
            "passed_filters": passed_filters,
            "new_entries": len(new_symbols),
            "dropped": len(dropped_symbols),
            "avg_days_on_list": round(avg_days, 1),
        },
        "ttl": 7776000,  # 90 days
    }

    try:
        cosmos.write_dgi_snapshot(snapshot)
    except Exception as e:
        logger.error("Failed to write DGI snapshot: %s", e)

    summary = {
        "run_date": run_date,
        "total_screened": total_screened,
        "passed_filters": passed_filters,
        "top_n": len(top_entries),
        "new_entries": new_symbols,
        "dropped": dropped_symbols,
        "avg_days_on_list": round(avg_days, 1),
        "top_entries": [
            {
                "rank": e["rank"],
                "symbol": e["symbol"],
                "score": e["quality_score"],
                "category": e["category"],
                "days_on_list": e["days_on_list"],
            }
            for e in top_entries
        ],
    }

    logger.info(
        "DGI Screener complete: %d screened, %d passed, %d in top list, "
        "%d new, %d dropped",
        total_screened, passed_filters, len(top_entries),
        len(new_symbols), len(dropped_symbols),
    )
    return summary
