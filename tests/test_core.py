from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from eth_whale_extractor.core import (
    Source,
    SourcePool,
    collect_from_pool,
    extract_whales_from_records,
    load_address_candidates_from_sources,
    normalize_address,
    parse_records,
    write_whales_csv,
)


def test_fresh_source_default_is_considered_fresh():
    src = Source(name="fresh", url="https://example.com", verified_at="2026-05-21T12:33:34Z", freshness_days=30)
    assert load_address_candidates_from_sources([src], fetch_text=lambda *a, **k: '[]') == []


def test_normalize_address_lowercases_and_validates():
    assert normalize_address("0x52908400098527886E0F7030069857D2E4169EE7") == (
        "0x52908400098527886e0f7030069857d2e4169ee7"
    )


def test_parse_records_from_csv_with_eth_values():
    text = "address,balance_eth\n0x1111111111111111111111111111111111111111,12.5\n0x2222222222222222222222222222222222222222,30\n"
    rows = list(parse_records(text, source_name="csv-source", format_hint="csv"))
    assert rows[0]["address"] == "0x1111111111111111111111111111111111111111"
    assert rows[1]["balance_eth"] == pytest.approx(30.0)


def test_parse_records_from_json_array_with_wei_string():
    text = json.dumps(
        [
            {"address": "0x3333333333333333333333333333333333333333", "balance_wei": "25000000000000000000"},
            {"address": "0x4444444444444444444444444444444444444444", "balance_wei": "26000000000000000000"},
        ]
    )
    rows = list(parse_records(text, source_name="json-source", format_hint="json"))
    assert rows[0]["balance_eth"] == pytest.approx(25.0)
    assert rows[1]["balance_eth"] == pytest.approx(26.0)


def test_parse_records_from_ndjson():
    text = """{"address":"0x5555555555555555555555555555555555555555","balance_eth":26}\n{"address":"0x6666666666666666666666666666666666666666","balance_eth":27}\n"""
    rows = list(parse_records(text, source_name="ndjson-source", format_hint="ndjson"))
    assert len(rows) == 2
    assert rows[0]["address"] == "0x5555555555555555555555555555555555555555"


def test_load_address_candidates_from_sources_merges_and_dedupes():
    source_a = Source(name="a", url="https://a.example", format_hint="csv")
    source_b = Source(name="b", url="https://b.example", format_hint="json")
    samples = {
        "https://a.example": "address,label\n0x1111111111111111111111111111111111111111,foo\n0x2222222222222222222222222222222222222222,bar\n",
        "https://b.example": json.dumps([
            {"address": "0x1111111111111111111111111111111111111111", "name": "dup"},
            {"address": "0x3333333333333333333333333333333333333333", "name": "baz"},
        ]),
    }

    def fetch(url, headers=None, timeout=20):
        return samples[url]

    rows = list(load_address_candidates_from_sources([source_a, source_b], fetch_text=fetch))
    assert [r["address"] for r in rows] == [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0x3333333333333333333333333333333333333333",
    ]


def test_source_pool_rotates_and_respects_cooldown():
    pool = SourcePool(
        [
            Source(name="a", url="https://a.example", format_hint="json"),
            Source(name="b", url="https://b.example", format_hint="json"),
        ]
    )

    first = pool.next()
    pool.mark_failed(first, retry_after_seconds=10, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    second = pool.next(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert second.name == "b"


def test_collect_from_pool_uses_sleep_from_retry_after():
    pool = SourcePool([Source(name="a", url="https://a.example", format_hint="json")])

    sleeps: list[float] = []

    def fake_sleep(delay):
        sleeps.append(delay)

    with pytest.raises(RuntimeError):
        collect_from_pool(pool, attempts=1, sleep_fn=fake_sleep)

    assert sleeps and sleeps[0] >= 1


def test_write_whales_csv_respects_size_limit(tmp_path: Path):
    rows = [
        {"address": f"0x{i:040x}", "balance_eth": float(100 + i), "source": "x", "snapshot_ts": "2026-01-01T00:00:00Z", "metadata": {}}
        for i in range(50000)
    ]
    out = tmp_path / "whales.csv"
    stats = write_whales_csv(rows, out, max_output_mb=1)
    assert out.exists()
    assert stats["written_rows"] > 0
    assert stats["truncated"] is True
    assert out.stat().st_size <= 1_000_000 + 8192


def test_extract_whales_from_records_filters_above_threshold():
    records = [
        {"address": "0x5555555555555555555555555555555555555555", "balance_eth": 24.99, "source": "x"},
        {"address": "0x6666666666666666666666666666666666666666", "balance_eth": 25.0, "source": "x"},
        {"address": "0x7777777777777777777777777777777777777777", "balance_eth": 27.2, "source": "x"},
    ]
    rows = extract_whales_from_records(records, threshold_eth=25.0, snapshot_ts="2026-01-01T00:00:00Z")
    assert [r["address"] for r in rows] == ["0x7777777777777777777777777777777777777777"]
    assert rows[0]["balance_eth"] == pytest.approx(27.2)
    assert rows[0]["snapshot_ts"] == "2026-01-01T00:00:00Z"
