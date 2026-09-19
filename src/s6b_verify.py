"""Stage 6b - verify every operator's link count against the API, repair mismatches.

Stage 6 pages through each operator's vehicles. This pass asks the API for each
done operator's authoritative `count` (a one-row query, so it is cheap) and
compares it with what is on disk. Operators that disagree are dropped from
links.done and their rows removed from links.jsonl, so re-running stage 6
refetches them cleanly.

Resumable: every verified operator is appended to links.verify with the count the
API reported, so an interrupted pass continues instead of starting over.

  python s6b_verify.py                 report only
  python s6b_verify.py --repair        rewrite links.jsonl / links.done for mismatches
  python s6b_verify.py --sample 2000   verify a seeded random subset instead of all

--sample trades completeness for time: the API answers roughly 5-10 of these a
second, so a full pass over 24k operators is ~1 hour. A 2,000-operator sample
detects a 1 % truncation rate with ~20 hits, which is enough to decide whether
a full pass is needed at all.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from collections import Counter

from common import PageFailed, RAW, client, seop_page

OUTFILE = RAW / "links.jsonl"
DONEFILE = RAW / "links.done"
VERIFYFILE = RAW / "links.verify"
CONCURRENCY = 24


def stored_counts() -> Counter:
    c: Counter = Counter()
    if not OUTFILE.exists():
        return c
    with OUTFILE.open(encoding="utf-8") as fh:
        for line in fh:
            # cheap key extraction - avoids json-parsing 900k full rows
            i = line.find('"operador_id": ')
            if i < 0:
                continue
            j = line.find(",", i)
            try:
                c[int(line[i + 15:j])] += 1
            except ValueError:
                continue
    return c


def load_verified() -> dict[int, int]:
    out: dict[int, int] = {}
    if VERIFYFILE.exists():
        for line in VERIFYFILE.read_text(encoding="utf-8").splitlines():
            if "\t" in line:
                op, n = line.split("\t", 1)
                out[int(op)] = int(n)
    return out


async def main() -> None:
    repair = "--repair" in sys.argv
    done = sorted({int(x) for x in DONEFILE.read_text().split() if x.strip()}) \
        if DONEFILE.exists() else []
    have = stored_counts()
    expected = load_verified()
    todo = [op for op in done if op not in expected]
    if "--sample" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sample") + 1])
        random.seed(20260919)
        todo = sorted(random.sample(todo, min(n, len(todo))))
        done = [op for op in done if op in expected or op in set(todo)]
    print(f"[s6b] operadores done {len(done)} | already verified {len(expected)} | to verify {len(todo)}",
          flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    unresolved: list[int] = []
    checked = 0

    if todo:
        with VERIFYFILE.open("a", encoding="utf-8") as vfh:
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
                        vfh.write(f"{op}\t{total}\n")
                        checked += 1
                        if checked % 500 == 0:
                            vfh.flush()
                            print(f"[s6b] verified {checked}/{len(todo)}", flush=True)

                await asyncio.gather(*(one(o) for o in todo))

    bad = sorted(op for op in done if op in expected and have.get(op, 0) != expected[op])
    short = [op for op in bad if have.get(op, 0) < expected[op]]
    over = [op for op in bad if have.get(op, 0) > expected[op]]
    missing = sum(expected[op] - have.get(op, 0) for op in short)

    print()
    print(f"[s6b] verified this run      {checked}")
    print(f"[s6b] unresolved (retry)     {len(unresolved)}")
    print(f"[s6b] match                  {len(done) - len(bad) - len(unresolved)}")
    print(f"[s6b] short (truncated)      {len(short)}  ({missing} links missing)")
    print(f"[s6b] over (duplicate rows)  {len(over)}  - harmless, s9 dedupes on link_id")

    if not repair:
        print("\n[s6b] report only. Use --repair to fix.")
        return
    drop = set(short) | set(unresolved)
    if not drop:
        print("\n[s6b] nothing to repair.")
        return

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
    DONEFILE.write_text("".join(f"{o}\n" for o in done if o not in drop), encoding="utf-8")
    for op in drop:                          # force re-verification after refetch
        expected.pop(op, None)
    VERIFYFILE.write_text("".join(f"{o}\t{n}\n" for o, n in expected.items()), encoding="utf-8")

    print(f"\n[s6b] REPAIRED: {len(drop)} operators queued for refetch, {kept} links kept")
    print("[s6b] run s6_links.py again to recover them.")


if __name__ == "__main__":
    asyncio.run(main())
