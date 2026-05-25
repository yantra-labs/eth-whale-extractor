from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

WEI_PER_ETH = Decimal("1000000000000000000")
DEFAULT_USER_AGENT = "eth-whale-extractor/0.1"
DEFAULT_TIMEOUT_SECONDS = 20


@dataclass(slots=True)
class Source:
    name: str
    url: str
    format_hint: str = "json"
    headers: Dict[str, str] = field(default_factory=dict)
    cooldown_seconds: int = 0


@dataclass(slots=True)
class SourceState:
    available_at: float = 0.0
    fail_count: int = 0


class SourcePool:
    def __init__(self, sources: Iterable[Source]):
        self._sources = list(sources)
        if not self._sources:
            raise ValueError("at least one source is required")
        self._states: Dict[str, SourceState] = {src.name: SourceState() for src in self._sources}
        self._cursor = 0

    def next(self, now: Optional[datetime] = None) -> Source:
        ts = (now or datetime.now(timezone.utc)).timestamp()
        for _ in range(len(self._sources)):
            src = self._sources[self._cursor]
            self._cursor = (self._cursor + 1) % len(self._sources)
            if self._states[src.name].available_at <= ts:
                return src
        return min(self._sources, key=lambda s: self._states[s.name].available_at)

    def mark_failed(self, source: Source, retry_after_seconds: int = 60, now: Optional[datetime] = None) -> None:
        ts = (now or datetime.now(timezone.utc)).timestamp()
        state = self._states[source.name]
        state.fail_count += 1
        state.available_at = ts + max(1, retry_after_seconds)

    def mark_success(self, source: Source) -> None:
        self._states[source.name] = SourceState()


def normalize_address(address: str) -> str:
    if not isinstance(address, str):
        raise ValueError("address must be a string")
    addr = address.strip().lower()
    if not addr.startswith("0x") or len(addr) != 42:
        raise ValueError(f"invalid ethereum address: {address!r}")
    hex_part = addr[2:]
    if any(c not in "0123456789abcdef" for c in hex_part):
        raise ValueError(f"invalid ethereum address: {address!r}")
    return addr


def wei_to_eth(value: Any) -> float:
    if value is None:
        raise ValueError("balance is missing")
    if isinstance(value, (int, float, Decimal)):
        dec = Decimal(str(value))
    else:
        dec = Decimal(str(value).strip())
    return float(dec / WEI_PER_ETH)


def _extract_balance(record: Dict[str, Any]) -> float:
    for key in ("balance_eth", "balance", "eth_balance"):
        if key in record and record[key] not in (None, ""):
            return float(Decimal(str(record[key])))
    for key in ("balance_wei", "wei_balance"):
        if key in record and record[key] not in (None, ""):
            return wei_to_eth(record[key])
    raise ValueError("record missing balance field")


def _extract_address(record: Dict[str, Any]) -> str:
    for key in ("address", "wallet", "account"):
        if key in record and record[key]:
            return normalize_address(str(record[key]))
    raise ValueError("record missing address field")


def parse_records(text: str, source_name: str, format_hint: str = "json") -> Iterator[Dict[str, Any]]:
    fmt = format_hint.lower()
    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            yield {
                "address": _extract_address(row),
                "balance_eth": _extract_balance(row),
                "source": source_name,
                "raw": row,
            }
        return

    if fmt in {"ndjson", "jsonl"}:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            yield {
                "address": _extract_address(item),
                "balance_eth": _extract_balance(item),
                "source": source_name,
                "raw": item,
            }
        return

    payload = json.loads(text)
    items = payload if isinstance(payload, list) else payload.get("data") or payload.get("results") or []
    for item in items:
        if not isinstance(item, dict):
            continue
        yield {
            "address": _extract_address(item),
            "balance_eth": _extract_balance(item),
            "source": source_name,
            "raw": item,
        }


def extract_whales_from_records(
    records: Iterable[Dict[str, Any]],
    threshold_eth: float = 25.0,
    snapshot_ts: Optional[str] = None,
) -> List[Dict[str, Any]]:
    snapshot = snapshot_ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out: List[Dict[str, Any]] = []
    for row in records:
        balance = float(row["balance_eth"])
        if balance > threshold_eth:
            out.append(
                {
                    "address": normalize_address(row["address"]),
                    "balance_eth": round(balance, 18),
                    "source": row.get("source", "unknown"),
                    "snapshot_ts": snapshot,
                    "metadata": row.get("metadata", {}),
                }
            )
    out.sort(key=lambda r: (-r["balance_eth"], r["address"]))
    return out


def _rate_limit_sleep(source: Source, attempt: int) -> float:
    base = max(1, source.cooldown_seconds or 3)
    return min(60.0, float(base * (2 ** max(0, attempt - 1))))


def fetch_url(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    req_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json,text/plain,*/*"}
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_records_from_source(source: Source, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> List[Dict[str, Any]]:
    text = fetch_url(source.url, headers=source.headers, timeout=timeout)
    return list(parse_records(text, source_name=source.name, format_hint=source.format_hint))


def _http_retry_delay(exc: Exception, source: Source, attempt: int) -> float:
    if isinstance(exc, HTTPError):
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return min(120.0, float(retry_after))
            except ValueError:
                pass
        if exc.code in (429, 503):
            return _rate_limit_sleep(source, attempt)
    if isinstance(exc, URLError):
        return _rate_limit_sleep(source, attempt)
    return _rate_limit_sleep(source, attempt)


def collect_from_pool(
    pool: SourcePool,
    attempts: int = 1,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    sleep_fn=time.sleep,
) -> List[Dict[str, Any]]:
    errors: List[str] = []
    for attempt in range(1, attempts + 1):
        source = pool.next()
        try:
            records = load_records_from_source(source, timeout=timeout)
            pool.mark_success(source)
            return records
        except Exception as exc:
            delay = _http_retry_delay(exc, source, attempt)
            pool.mark_failed(source, retry_after_seconds=int(delay))
            errors.append(f"{source.name}: {exc}")
            logger.warning("source failed %s; retry_after=%s", source.name, delay)
            sleep_fn(delay)
    raise RuntimeError("all sources failed: " + " | ".join(errors))


def stable_record_id(address: str, source: str) -> str:
    return hashlib.sha256(f"{normalize_address(address)}|{source}".encode("utf-8")).hexdigest()[:16]
