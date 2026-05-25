from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    Source,
    extract_whales_from_records,
    load_address_candidates_from_sources,
    parse_records,
    write_whales_csv,
)

DEFAULT_SOURCES = [
    Source(name="eth-labels-accounts", url="https://raw.githubusercontent.com/dawsbot/eth-labels/v1/data/csv/accounts.csv", format_hint="csv", cooldown_seconds=10, repo="dawsbot/eth-labels", freshness_days=30, verified_at="2026-05-21T12:33:34Z"),
    Source(name="eth-labels-tokens", url="https://raw.githubusercontent.com/dawsbot/eth-labels/v1/data/csv/tokens.csv", format_hint="csv", cooldown_seconds=10, repo="dawsbot/eth-labels", freshness_days=30, verified_at="2026-05-21T12:33:34Z"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Ethereum wallet whales above a threshold.")
    parser.add_argument("--threshold-eth", type=float, default=25.0)
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--source-format", choices=["json", "csv", "ndjson"], default="csv")
    parser.add_argument("--local-file", help="Load records from a local JSON/CSV file instead of remote sources")
    parser.add_argument("--output", default="-", help="Output path, or - for stdout")
    parser.add_argument("--format", choices=["json", "csv"], default="csv")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--max-output-mb", type=int, default=100)
    parser.add_argument("--candidate-only", action="store_true", help="Only export merged address candidates without threshold filtering")
    return parser


def _load_local_file(path: str, source_format: str):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    source = Source(name=p.stem, url=str(p), format_hint=source_format)
    return list(parse_records(text, source_name=source.name, format_hint=source.format_hint))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.local_file:
        records = _load_local_file(args.local_file, args.source_format)
    else:
        sources = list(DEFAULT_SOURCES)
        for idx, url in enumerate(args.source_url):
            sources.append(Source(name=f"custom-{idx+1}", url=url, format_hint=args.source_format, cooldown_seconds=30))
        records = load_address_candidates_from_sources(sources)

    if args.candidate_only:
        whales = [{"address": r["address"], "balance_eth": float(r.get("balance_eth", 0) or 0), "source": r.get("source", "unknown"), "snapshot_ts": r.get("snapshot_ts") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "metadata": r.get("metadata", {})} for r in records]
    else:
        whales = extract_whales_from_records(records, threshold_eth=args.threshold_eth)

    if args.output == "-":
        if args.format == "json":
            payload = json.dumps(whales, indent=2, ensure_ascii=False)
            sys.stdout.write(payload + "\n")
        else:
            import tempfile
            tmp = Path(tempfile.gettempdir()) / "eth-whale-extractor.stdout.csv"
            stats = write_whales_csv(whales, tmp, max_output_mb=args.max_output_mb)
            sys.stdout.write(tmp.read_text(encoding="utf-8"))
            return 0 if not stats['truncated'] else 0
    else:
        if args.format == "json":
            Path(args.output).write_text(json.dumps(whales, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            write_whales_csv(whales, args.output, max_output_mb=args.max_output_mb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
