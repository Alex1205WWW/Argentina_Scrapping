"""Stage 3 - dump the complete CNRT vehicle registry (parque movil).

/v1/parquesMoviles is every vehicle CNRT holds, passenger and cargo, Argentine
and foreign MERCOSUR. Cargo units carry their detail under parqueMovilSimplificado
(tipoVehiculo SEMIRREMOLQUE / TRACTOR / CAMION / ACOPLADO, axle count, body type),
buses under carroceria. Only the fields the freight database needs are kept.

Resumable: every completed page offset is appended to parque_movil.offsets, so a
re-run only fetches what is missing.
"""
from __future__ import annotations

import asyncio
import json

from common import PAGE, RAW, client, seop_page

OUTFILE = RAW / "parque_movil.jsonl"
DONEFILE = RAW / "parque_movil.offsets"
CONCURRENCY = 20


def _d(o, *path):
    for p in path:
        if not isinstance(o, dict):
            return None
        o = o.get(p)
    return o


def flatten(r: dict) -> dict:
    s = r.get("parqueMovilSimplificado") or {}
    car = r.get("carroceria") or {}
    return {
        "parque_movil_id": r.get("id"),
        "dominio": (r.get("dominio") or "").strip().upper(),
        "anio_modelo": r.get("anioModelo"),
        "nro_chasis": r.get("nroChasis"),
        "nro_motor": r.get("nroMotor"),
        "pais": _d(r, "pais", "abrev"),
        "pais_desc": _d(r, "pais", "descripcion"),
        "tipo_vehiculo": _d(s, "tipoVehiculo", "descripcion") or _d(car, "tipoVehiculo", "descripcion"),
        "tipo_vehiculo_abrev": _d(s, "tipoVehiculo", "abrev") or _d(car, "tipoVehiculo", "abrev"),
        "cantidad_ejes": s.get("cantidadEjes") or _d(r, "carroceriaChasis", "chasis", "cantEjes"),
        "marca": _d(s, "chasisMarca", "descripcion")
                 or _d(r, "carroceriaChasis", "chasis", "chasisModelo", "chasisMarca", "descripcion"),
        "modelo": _d(s, "chasisModelo", "descripcion")
                  or _d(r, "carroceriaChasis", "chasis", "chasisModelo", "descripcion"),
        "tipo_carroceria": _d(s, "tipoCarroceria", "descripcion") or _d(car, "tipoCarroceria", "descripcion"),
        "carroceria_marca": _d(s, "carroceriaMarca", "descripcion") or _d(car, "carroceriaMarca", "descripcion"),
        "peso_vacio": _d(s, "vehiculoCargaDefault", "pesoVacio"),
        "carga_util": _d(s, "vehiculoCargaDefault", "cargaUtil"),
        "peso_maximo": _d(s, "vehiculoCargaDefault", "pesoMaximo"),
        "cant_asientos": r.get("cantAsientos"),
    }


async def main() -> None:
    done_offsets: set[int] = set()
    if DONEFILE.exists():
        done_offsets = {int(x) for x in DONEFILE.read_text().split() if x.strip()}

    async with client(limit=CONCURRENCY, timeout=120.0) as cli:
        _, total = await seop_page(cli, "parquesMoviles", 0, limit=1)
        offsets = [o for o in range(0, total, PAGE) if o not in done_offsets]
        print(f"[s3] total={total} pages_done={len(done_offsets)} pages_todo={len(offsets)}", flush=True)

        sem = asyncio.Semaphore(CONCURRENCY)
        lock = asyncio.Lock()
        done = 0

        with OUTFILE.open("a", encoding="utf-8") as fh, DONEFILE.open("a", encoding="utf-8") as dfh:
            async def one(off: int) -> None:
                nonlocal done
                async with sem:
                    res, _ = await seop_page(cli, "parquesMoviles", off)
                if not res:
                    return
                async with lock:
                    for r in res:
                        fh.write(json.dumps(flatten(r), ensure_ascii=False) + "\n")
                    dfh.write(str(off) + "\n")
                    done += 1
                    if done % 200 == 0:
                        fh.flush()
                        dfh.flush()
                        print(f"[s3] {done}/{len(offsets)} pages this run", flush=True)

            await asyncio.gather(*(one(o) for o in offsets))

    n = sum(1 for _ in OUTFILE.open(encoding="utf-8"))
    print(f"[s3] DONE rows={n} (target {total}) -> {OUTFILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
