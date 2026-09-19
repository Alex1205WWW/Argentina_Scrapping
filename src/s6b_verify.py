"""Stage 6b - verify every operator's link count against the API, repair mismatches.

Stage 6 pages through each operator's vehicles. If a page had failed silently the
operator would be stored with a truncated fleet and still marked done, and the
error would be invisible downstream. This pass asks the API for each done
operator's authoritative `count` (a one-row query, so it is cheap) and compares
it with what is on disk.

Operators that disagree are dropped from links.done and their rows are removed
from links.jsonl, so re-running stage 6 refetches them cleanly.

  python s6b_verify.py          report only
  python s6b_verify.py --repair rewrite links.jsonl / links.done
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter

from common import PageFailed, RAW, client, seop_page

OUTFILE = RAW / "links.jsonl"
DONEFILE = RAW / "links.done"
CONCURRENCY = 16


def stored_counts() -> Counter:
    c: Counter = Counter()
    if not OUTFILE.exists():
        return c
    with OUTFILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                c[json.loads(line)["operador_id"]] += 1
            except (json.JSONDecodeError, KeyError):
                continue
    return c


async def main() -> None:
    repair = "--repair" in sys.argv
    done = [int(x) for x in DONEFILE.read_text().split() if x.strip()] if DONEFILE.exists() else []
    done = sorted(set(done))
    have = stored_counts()
    print(f"[s6b] operadores marcados done: {len(done)} | con filas: {len(have)}", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    expected: dict[int, int] = {}
    unresolved: list[int] = []
    checked = 0
    lock = asyncio.Lock()

    async with client(limit=CONCURRENCY, timeout=90.0) as cli:
        async def one(op: int) -> None:
            nonlocal checked
            try:
                async with sem:
                    _, total = await seop_page(cli, "parquesMovilesOperadores", 0,
                                               limit=1, operador=op)
            except PageFailed:
                async with lock:
                    unresolved.append(op)
                return
            async with lock:
                expected[op] = total
                checked += 1
                if checked % 2000 == 0:
                    print(f"[s6b] verificados {checked}/{len(done)}", flush=True)

        await asyncio.gather(*(one(o) for o in done))

    bad = sorted(op for op, exp in expected.items() if have.get(op, 0) != exp)
    short = [op for op in bad if have.get(op, 0) < expected[op]]
    over = [op for op in bad if have.get(op, 0) > expected[op]]
    missing = sum(expected[op] - have.get(op, 0) for op in short)

    print()
    print(f"[s6b] verificados        {checked}")
    print(f"[s6b] sin resolver       {len(unresolved)}")
    print(f"[s6b] coinciden          {checked - len(bad)}")
    print(f"[s6b] incompletos        {len(short)}  (faltan {missing} vinculos)")
    print(f"[s6b] con filas de mas   {len(over)}")

    if not repair:
        print("\n[s6b] modo reporte. Use --repair para reparar.")
        return
    if not bad and not unresolved:
        print("\n[s6b] nada que reparar.")
        return

    drop = set(bad) | set(unresolved)
    kept = 0
    tmp = OUTFILE.with_suffix(".jsonl.tmp")
    with OUTFILE.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            s = line.strip()
            if not s:
                continue
            try:
                if json.loads(s)["operador_id"] in drop:
                    continue
            except (json.JSONDecodeError, KeyError):
                continue
            dst.write(line)
            kept += 1
    tmp.replace(OUTFILE)

    keep_done = [op for op in done if op not in drop]
    DONEFILE.write_text("".join(f"{o}\n" for o in keep_done), encoding="utf-8")

    print(f"\n[s6b] REPARADO: {len(drop)} operadores marcados para refetch, "
          f"{kept} vinculos conservados, done={len(keep_done)}")
    print("[s6b] volver a ejecutar s6_links.py para recuperarlos.")


if __name__ == "__main__":
    asyncio.run(main())
