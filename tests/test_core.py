from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from eth_whale_extractor.core import (
    Source,
    SourcePool,
    collect_from_pool,
    extract_whales_from_records,
    normalize_address,
    parse_records,
)


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

    def fake_load(source, timeout=20):
        raise RuntimeError("boom")

    def fake_sleep(delay):
        sleeps.append(delay)

    with pytest.raises(RuntimeError):
        collect_from_pool(pool, attempts=1, sleep_fn=fake_sleep)

    assert sleeps and sleeps[0] >= 1


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
