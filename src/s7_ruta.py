"""Stage 7 - validate each plate against RUTA (Registro Unico del Transporte Automotor).

RUTA is the national freight registry. CNRT exposes it per-plate at
/api/ruta_vigente_por_dominio/{dominio}.json, answering with the current
constancia (nroConstancia / nroCertificado / fechaAlta / fechaValidacion) or a
404 when the plate holds no live RUTA. That 200-vs-404 is the authoritative
"is this freight plate active in RUTA" test.

Input plates come from the CNRT parque movil dump (stage 3), restricted to
Argentine plates. Resumable via ruta.done.
"""
from __future__ import annotations

import asyncio
import json
import sys

from common import UNRESOLVED, Jsonl, RAW, client, get_json

CONSULTAPME = "https://consultapme.cnrt.gob.ar/api"
IN_PARQUE = RAW / "parque_movil.jsonl"
OUTFILE = RAW / "ruta.jsonl"
CONCURRENCY = 40

CARGO_TYPES = {"SEMIRREMOLQUE", "TRACTOR", "CAMION", "CAMIÓN", "ACOPLADO",
               "BATEA", "CARRETON", "CARRETÓN", "CAMIONETA"}


def load_plates(only_cargo: bool = True, tipo: str | None = None) -> list[str]:
    """Argentine plates from the CNRT registry, optionally one vehicle type only."""
    plates: set[str] = set()
    with IN_PARQUE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("pais") != "AR":
                continue
            tv = (r.get("tipo_vehiculo") or "").upper()
            if tipo and tv != tipo.upper():
                continue
            if only_cargo and tv not in CARGO_TYPES:
                continue
            d = (r.get("dominio") or "").strip().upper()
            if d:
                plates.add(d)
    return sorted(plates)


def _dt(v):
    return v.get("date") if isinstance(v, dict) else v


async def main() -> None:
    only_cargo = "--all" not in sys.argv
    tipo = None
    for a in sys.argv[1:]:
        if a.startswith("--tipo="):
            tipo = a.split("=", 1)[1]
    plates = load_plates(only_cargo, tipo)

    with Jsonl(OUTFILE, "dominio") as sink:
        done = sink.done_keys()
        todo = [p for p in plates if p not in done]
        print(f"[s7] plates {len(plates)} | done {len(done)} | todo {len(todo)}", flush=True)

        sem = asyncio.Semaphore(CONCURRENCY)
        lock = asyncio.Lock()
        processed = vigentes = unresolved = 0

        async with client(limit=CONCURRENCY, timeout=60.0) as cli:
            async def one(dom: str) -> None:
                nonlocal processed, vigentes, unresolved
                async with sem:
                    data = await get_json(cli, f"{CONSULTAPME}/ruta_vigente_por_dominio/{dom}.json")
                if data is UNRESOLVED:
                    # never settled - leave it unrecorded so a resume retries it
                    async with lock:
                        unresolved += 1
                    return
                async with lock:
                    processed += 1
                    if isinstance(data, dict) and data.get("nroConstancia"):
                        sink.write({
                            "dominio": dom,
                            "ruta_vigente": True,
                            "nro_constancia": data.get("nroConstancia"),
                            "nro_certificado": data.get("nroCertificado"),
                            "serie_certificado": data.get("serieCertificado"),
                            "provisoria": data.get("provisoria"),
                            "fecha_alta": _dt(data.get("fechaAlta")),
                            "fecha_validacion": _dt(data.get("fechaValidacion")),
                        })
                        vigentes += 1
                    else:
                        sink.write({"dominio": dom, "ruta_vigente": False})
                    if processed % 2000 == 0:
                        sink.flush()
                        print(f"[s7] {processed}/{len(todo)} | RUTA vigente {vigentes} | sin resolver {unresolved}", flush=True)

            await asyncio.gather(*(one(p) for p in todo))

    print(f"[s7] DONE processed={processed} ruta_vigente={vigentes} unresolved={unresolved} -> {OUTFILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
