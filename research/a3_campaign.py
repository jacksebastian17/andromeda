"""Run with python -m research.a3_campaign. CLI output is aggregate-only."""

import argparse
import json
import os
import sys
from collections import Counter

from .a3_data import PLAN, collect, instant
from .a3_quality import summarize, write_outputs
from .a3_transport import HOST, ROOT, Archive, Stop, exclusive

SERIES = {name: cfg["series"] for name, cfg in PLAN["cohorts"].items()}
CAMPAIGN = PLAN["campaign"]


def discovery(archive):
    result = {}
    cutoff = archive.get("/historical/cutoff")
    result["cutoff_fields_present"] = {
        k: isinstance(cutoff.get(k), str) for k in ("market_settled_ts", "trades_created_ts")
    }
    for cohort, series in SERIES.items():
        item = result[cohort] = {}
        try:
            info = archive.get(f"/series/{series}").get("series", {})
            item["series_confirmed"] = isinstance(info, dict) and info.get("ticker") == series
            page = archive.get("/historical/markets", series_ticker=series, limit=100)
            markets = page.get("markets")
            if not isinstance(markets, list) or not all(isinstance(m, dict) for m in markets):
                raise Stop("malformed_list")
            item["rows"] = len(markets)
            item["more_pages"] = bool(page.get("cursor"))
            item["settlement_months"] = dict(
                Counter(
                    parsed.strftime("%Y-%m")
                    for m in markets
                    if (parsed := instant(m.get("settlement_ts"))) is not None
                )
            )
            item["open_months"] = dict(
                Counter(
                    parsed.strftime("%Y-%m")
                    for m in markets
                    if (parsed := instant(m.get("open_time"))) is not None
                )
            )
        except Stop as exc:
            item["error"] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["discover", "collect", "replay", "status"])
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise Stop("local_campaign_only")
    with exclusive(ROOT):
        if args.action in ("replay", "status") and not (ROOT / "acquisition.sqlite").is_file():
            raise Stop("archive_absent")
        archive = Archive(ROOT, offline=args.action in ("replay", "status"))
        try:
            archive.bind("identity", [CAMPAIGN, HOST, SERIES])
            if args.action == "discover":
                data = discovery(archive)
            elif args.action in ("collect", "replay"):
                packets, frame = collect(archive)
                features, labels, data = summarize(packets, frame)
                manifest = {
                    "cohorts": data,
                    "transport": archive.stats(),
                    "cutoff_snapshot": archive.get("/historical/cutoff"),
                    "origin": PLAN["origin"],
                    "documented_openapi": "3.38.0",
                    "api_path_version": "v2",
                    "requests": archive.receipts(),
                }
                write_outputs(ROOT, features, labels, manifest)
            else:
                data = {}
            print(json.dumps({"result": data, "transport": archive.stats()}, indent=2))
        finally:
            archive.db.close()


if __name__ == "__main__":
    try:
        main()
    except Stop as exc:
        print(json.dumps({"stopped": str(exc)}))
        sys.exit(2)
    except Exception as exc:
        # Never emit a traceback, HTTP response, URL with IDs, or record values.
        print(json.dumps({"stopped": type(exc).__name__}))
        sys.exit(1)
