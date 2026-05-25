from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from .core import (
    Source,
    SourcePool,
    collect_from_pool,
    extract_whales_from_records,
    load_records_from_source,
)

DEFAULT_SOURCES = [
    Source(
        name="etherscan-public",
        url="https://raw.githubusercontent.com/eth-educational-data/public-wallet-samples/main/wallets.json",
        format_hint="json",
        cooldown_seconds=10,
    ),
    Source(
        name="blockchair-public",
        url="https://raw.githubusercontent.com/eth-educational-data/public-wallet-samples/main/wallets.csv",
        format_hint="csv",
        cooldown_seconds=15,
    ),
    Source(
        name="explorer-mirror",
        url="https://raw.githubusercontent.com/eth-educational-data/public-wallet-samples/main/wallets.ndjson",
        format_hint="json",
        cooldown_seconds=20,
    ),
]


def _load_local_file(path: str):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".csv":
        source = Source(name=p.stem, url=str(p), format_hint="csv")
    else:
        source = Source(name=p.stem, url=str(p), format_hint="json")
    return list(load_records_from_text(text, source))


def load_records_from_text(text: str, source: Source):
    from .core import parse_records

    return list(parse_records(text, source_name=source.name, format_hint=source.format_hint))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Ethereum wallet whales above a threshold.")
    parser.add_argument("--threshold-eth", type=float, default=25.0)
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--source-format", choices=["json", "csv"], default="json")
    parser.add_argument("--local-file", help="Load records from a local JSON/CSV file instead of remote sources")
    parser.add_argument("--output", default="-", help="Output path, or - for stdout")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--attempts", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.local_file:
        source = Source(name=Path(args.local_file).stem, url=args.local_file, format_hint=args.source_format)
        records = load_records_from_text(Path(args.local_file).read_text(encoding="utf-8"), source)
    else:
        sources = list(DEFAULT_SOURCES)
        for idx, url in enumerate(args.source_url):
            sources.append(Source(name=f"custom-{idx+1}", url=url, format_hint=args.source_format, cooldown_seconds=30))
        pool = SourcePool(sources)
        records = collect_from_pool(pool, attempts=args.attempts)

    whales = extract_whales_from_records(records, threshold_eth=args.threshold_eth)

    if args.format == "json":
        payload = json.dumps(whales, indent=2, ensure_ascii=False)
    else:
        fieldnames = ["address", "balance_eth", "source", "snapshot_ts"]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in whales:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
        payload = output.getvalue().rstrip("\n")

    if args.output == "-":
        sys.stdout.write(payload + "\n")
    else:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
