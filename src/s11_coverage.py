"""Stage 11 - measure how much of RUTA the CNRT registry actually covers.

The CNRT vehicle registry can be enumerated; RUTA cannot (it answers per-plate
only). So the open question is whether CNRT's plate list *is* the national
freight fleet or only part of it. This estimates the answer instead of assuming
one.

Method - neighbour sampling. Argentine plates are issued sequentially, so plates
numerically adjacent to a known CNRT freight plate belong to the same issuance
era. For a random sample of known plates we take unseen neighbours, drop any that
CNRT already knows, and ask RUTA about them. A RUTA hit on a plate CNRT does not
hold is, by definition, a freight vehicle registered nationally but absent from
the CNRT registry.

  hits_outside_cnrt / (hits_outside_cnrt + known_cnrt_in_sample)

approximates the share of the national freight fleet CNRT is missing.

  python s11_coverage.py [sample_plates] [neighbours_each]
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys

from common import CNRT_API, RAW, UNRESOLVED, client, get_json

IN_PARQUE = RAW / "parque_movil.jsonl"
OUTFILE = RAW / "coverage_probe.jsonl"
CONCURRENCY = 20

OLD = re.compile(r"^([A-Z]{3})(\d{3})$")        # AAA123, issued to 2016
NEW = re.compile(r"^([A-Z]{2})(\d{3})([A-Z]{2})$")  # AB123CD, MERCOSUR


def neighbours(plate: str, span: int) -> list[str]:
    """Plates numerically adjacent to `plate`, same letter block."""
    out = []
    m = OLD.match(plate)
    if m:
        pre, num = m.group(1), int(m.group(2))
        for d in range(-span, span + 1):
            n = num + d
            if d and 0 <= n <= 999:
                out.append(f"{pre}{n:03d}")
        return out
    m = NEW.match(plate)
    if m:
        pre, num, suf = m.group(1), int(m.group(2)), m.group(3)
        for d in range(-span, span + 1):
            n = num + d
            if d and 0 <= n <= 999:
                out.append(f"{pre}{n:03d}{suf}")
    return out


def load_known() -> tuple[set[str], list[str]]:
    """All CNRT plates, and the Argentine cargo ones to sample around."""
    known: set[str] = set()
    cargo: list[str] = []
    cargo_types = {"SEMIRREMOLQUE", "TRACTOR", "CAMION", "CAMIÓN",
                   "ACOPLADO", "BATEA", "CARRETON", "CARRETÓN"}
    with IN_PARQUE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            d = (r.get("dominio") or "").strip().upper()
            if not d:
                continue
            known.add(d)
            if r.get("pais") == "AR" and (r.get("tipo_vehiculo") or "").upper() in cargo_types:
                cargo.append(d)
    return known, cargo


async def main() -> None:
    n_seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
    span = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    known, cargo = load_known()
    print(f"[s11] CNRT conoce {len(known):,} dominios | cargo AR {len(cargo):,}", flush=True)

    random.seed(20260919)
    seeds = random.sample(cargo, min(n_seed, len(cargo)))

    candidates: set[str] = set()
    for p in seeds:
        for nb in neighbours(p, span):
            if nb not in known:
                candidates.add(nb)
    candidates = sorted(candidates)
    print(f"[s11] {len(seeds):,} semillas -> {len(candidates):,} vecinos fuera del registro CNRT",
          flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    hits = checked = unresolved = 0
    found: list[dict] = []

    async with client(limit=CONCURRENCY, timeout=60.0) as cli:
        async def one(dom: str) -> None:
            nonlocal hits, checked, unresolved
            async with sem:
                d = await get_json(cli, f"{CNRT_API}/ruta_vigente_por_dominio/{dom}.json")
            if d is UNRESOLVED:
                async with lock:
                    unresolved += 1
                return
            async with lock:
                checked += 1
                if isinstance(d, dict) and d.get("nroConstancia"):
                    hits += 1
                    found.append({"dominio": dom, "nro_constancia": d.get("nroConstancia"),
                                  "nro_certificado": d.get("nroCertificado")})
                if checked % 1000 == 0:
                    print(f"[s11] {checked:,}/{len(candidates):,} | RUTA fuera de CNRT: {hits:,}",
                          flush=True)

        await asyncio.gather(*(one(c) for c in candidates))

    with OUTFILE.open("w", encoding="utf-8") as fh:
        for r in found:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    rate = hits / checked if checked else 0
    print()
    print(f"[s11] vecinos consultados          {checked:,}")
    print(f"[s11] sin resolver                 {unresolved:,}")
    print(f"[s11] con RUTA vigente             {hits:,}  ({rate:.1%} de los vecinos)")
    print(f"[s11] -> por cada dominio de carga en CNRT hay aprox. "
          f"{hits / len(seeds):.2f} vehiculos con RUTA vigente en su vecindario "
          f"que CNRT NO registra")
    print(f"[s11] detalle -> {OUTFILE}")


if __name__ == "__main__":
    asyncio.run(main())
