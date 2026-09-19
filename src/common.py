"""Shared plumbing for the CNRT / RUTA / DNRPA / ARCA scrapers.

Everything network-facing lives here so the stage scripts stay small:

  client()          async HTTP client with the headers the .gob.ar hosts expect
  get_json()        GET that tells a documented 404 apart from "never settled"
  seop_page()       one page of a paginated SEOP registry
  dump_collection() fetch a whole SEOP registry to JSONL in one call
  download()        stream a large file to disk (ARCA padron, DNRPA zips)
  Jsonl             append-only sink that can resume by replaying its keys
  dig()             safe nested-dict lookup for the deeply nested SEOP records
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "out"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

CNRT_API = "https://consultapme.cnrt.gob.ar/api"   # per-plate / per-CUIT lookups
SEOP = "https://api.cnrt.gob.ar/seop/public/v1"    # paginated registries
PAGE = 100  # SEOP hard-caps `limit` at 100 regardless of what we ask for

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
           "Accept-Language": "es-AR,es;q=0.9"}

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def client(timeout: float = 30.0, limit: int = 16) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        timeout=httpx.Timeout(timeout, connect=15.0),
        limits=httpx.Limits(max_connections=limit, max_keepalive_connections=limit),
        follow_redirects=True,
        http2=True,
    )


class Unresolved:
    """Sentinel: the request never produced a definitive answer.

    Distinct from None (a documented 404). A stage that records negative results
    must never treat a transport failure as "the resource does not exist" - it
    skips the key instead, so a resume retries it.
    """
    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNRESOLVED"


UNRESOLVED = Unresolved()


async def get_json(cli: httpx.AsyncClient, url: str, tries: int = 5) -> Any:
    """GET -> parsed JSON; None on a documented 404; UNRESOLVED if never settled."""
    for attempt in range(tries):
        try:
            r = await cli.get(url)
        except httpx.HTTPError:
            await asyncio.sleep(2 ** attempt + random.random())
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 200:
            try:
                return r.json()
            except json.JSONDecodeError:
                return UNRESOLVED
        if r.status_code in RETRY_STATUS:
            await asyncio.sleep(2 ** attempt + random.random())
            continue
        return UNRESOLVED
    return UNRESOLVED


def download(url: str, dest: Path, min_bytes: int = 1) -> None:
    """Stream a file to disk. Skips when a plausible copy is already there."""
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return
    print(f"    downloading {dest.name} ...", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.Client(headers=HEADERS, timeout=1800.0, follow_redirects=True) as c, \
            c.stream("GET", url) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.replace(dest)


# --------------------------------------------------------------------------
# SEOP pagination
# --------------------------------------------------------------------------
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


async def dump_collection(cli: httpx.AsyncClient, path: str,
                          flatten: Callable[[dict], dict], outfile: Path, *,
                          concurrency: int = 8, label: str = "", **params) -> int:
    """Fetch every page of a SEOP registry concurrently and write one JSONL row
    per record, deduplicated on `id`.

    Meant for the small registries (companies, operators): pages are held in
    memory so the file is written in offset order and never partially. A page
    that never settles is retried once at the end; if it still fails the run
    raises rather than leave a file that looks complete but is not.
    """
    tag = label or path
    _, total = await seop_page(cli, path, 0, limit=1, **params)
    offsets = list(range(0, total, PAGE))
    print(f"[{tag}] total={total} pages={len(offsets)}", flush=True)

    sem = asyncio.Semaphore(concurrency)
    pages: dict[int, list] = {}
    failed: list[int] = []

    async def one(off: int) -> None:
        try:
            async with sem:
                res, _ = await seop_page(cli, path, off, **params)
            pages[off] = res
        except PageFailed:
            failed.append(off)
        if len(pages) % 50 == 0:
            print(f"[{tag}] {len(pages)}/{len(offsets)} pages", flush=True)

    await asyncio.gather(*(one(o) for o in offsets))
    for off in failed:                       # second chance, sequential
        res, _ = await seop_page(cli, path, off, **params)
        pages[off] = res

    seen: set = set()
    with outfile.open("w", encoding="utf-8") as fh:
        for off in sorted(pages):
            for r in pages[off]:
                rid = r.get("id")
                if rid in seen:
                    continue
                seen.add(rid)
                fh.write(json.dumps(flatten(r), ensure_ascii=False) + "\n")
    print(f"[{tag}] DONE rows={len(seen)} (expected {total}) -> {outfile}", flush=True)
    return len(seen)


# --------------------------------------------------------------------------
# Records and files
# --------------------------------------------------------------------------
def dig(o: Any, *path: str) -> Any:
    """`dig(rec, "a", "b", "c")` == rec["a"]["b"]["c"], or None if any hop is missing."""
    for p in path:
        if not isinstance(o, dict):
            return None
        o = o.get(p)
    return o


def read_jsonl(path: Path):
    """Yield parsed rows, skipping blank or half-written lines."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


class Jsonl:
    """Append-only JSONL sink that can resume by replaying the keys already written."""

    def __init__(self, path: Path, key: str):
        self.path = path
        self.key = key
        self._fh = None

    def done_keys(self) -> set:
        return {r[self.key] for r in read_jsonl(self.path) if self.key in r}

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
