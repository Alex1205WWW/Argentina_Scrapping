"""Shared HTTP/session plumbing for the CNRT-RUTA / DNRPA / ARCA scrapers."""
from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any, Iterable

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "out"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

CNRT_API = "https://consultapme.cnrt.gob.ar/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
           "Accept-Language": "es-AR,es;q=0.9"}


def client(timeout: float = 30.0, limit: int = 32) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        timeout=httpx.Timeout(timeout, connect=15.0),
        limits=httpx.Limits(max_connections=limit, max_keepalive_connections=limit),
        follow_redirects=True,
        http2=True,
    )


class Unresolved:
    """Sentinel: the request never produced a definitive answer.

    Distinct from None (a documented 404). Callers that record negative results
    must not treat a transport failure as "the resource does not exist", or a
    blip becomes a wrong row; they should skip the key so a resume retries it.
    """
    __slots__ = ()

    def __bool__(self) -> bool:
        return False


UNRESOLVED = Unresolved()


async def get_json(cli: httpx.AsyncClient, url: str, tries: int = 5) -> Any | None:
    """GET -> parsed JSON, None on a documented 404, UNRESOLVED if never settled."""
    for attempt in range(tries):
        try:
            r = await cli.get(url)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                try:
                    return r.json()
                except json.JSONDecodeError:
                    return UNRESOLVED
            if r.status_code in (403, 408, 425, 429, 500, 502, 503, 504):
                await asyncio.sleep(2 ** attempt + random.random())
                continue
            return UNRESOLVED
        except (httpx.TransportError, httpx.HTTPError):
            await asyncio.sleep(2 ** attempt + random.random())
    return UNRESOLVED


class Jsonl:
    """Append-only JSONL sink that can resume by replaying the keys already written."""

    def __init__(self, path: Path, key: str):
        self.path = path
        self.key = key
        self._fh = None

    def done_keys(self) -> set:
        seen: set = set()
        if not self.path.exists():
            return seen
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen.add(json.loads(line)[self.key])
                except (json.JSONDecodeError, KeyError):
                    continue
        return seen

    def __enter__(self):
        self._fh = self.path.open("a", encoding="utf-8")
        return self

    def write(self, obj: dict) -> None:
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def flush(self) -> None:
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def __exit__(self, *exc):
        self._fh.flush()
        self._fh.close()


def chunks(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


SEOP = "https://api.cnrt.gob.ar/seop/public/v1"
PAGE = 100  # server hard-caps `limit` at 100 regardless of what we ask for


class PageFailed(RuntimeError):
    """A SEOP page never returned a definitive answer."""


async def seop_page(cli: httpx.AsyncClient, path: str, offset: int,
                    limit: int = PAGE, **params) -> tuple[list, int]:
    """One page of a SEOP collection -> (results, total count).

    Raises PageFailed when the request never settled, so a caller paging through
    a collection aborts instead of silently storing a truncated result.
    """
    q = {"limit": limit, "offset": offset, **params}
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    data = await get_json(cli, f"{SEOP}/{path}?{qs}")
    if data is UNRESOLVED:
        raise PageFailed(f"{path}?{qs}")
    if not isinstance(data, dict) or "data" not in data:
        return [], 0
    body = data["data"]
    total = body.get("metadata", {}).get("resultset", {}).get("count", 0)
    return body.get("results", []) or [], total
