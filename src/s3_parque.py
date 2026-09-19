"""Stage 3 - dump the complete CNRT vehicle registry (parque movil).

/v1/parquesMoviles is every vehicle CNRT holds, passenger and cargo, Argentine
and foreign MERCOSUR. Cargo units carry their detail under parqueMovilSimplificado
(tipoVehiculo SEMIRREMOLQUE / TRACTOR / CAMION / ACOPLADO, axle count, body type),
buses under carroceria. Only the fields the freight database needs are kept.

Resumable: every completed page offset is appended to parque_movil.offsets, so a
re-run only fetches what is missing. A page that never settles is left out of
that file (and reported), so it is retried on the next run rather than lost.
"""
from __future__ import annotations

import asyncio
import json

from common import PAGE, RAW, PageFailed, client, dig, seop_page

OUTFILE = RAW / "parque_movil.jsonl"
DONEFILE = RAW / "parque_movil.offsets"
CONCURRENCY = 20


def flatten(r: dict) -> dict:
    s = r.get("parqueMovilSimplificado") or {}
    car = r.get("carroceria") or {}
    chasis = dig(r, "carroceriaChasis", "chasis") or {}
    return {
        "parque_movil_id": r.get("id"),
        "dominio": (r.get("dominio") or "").strip().upper(),
        "anio_modelo": r.get("anioModelo"),
        "nro_chasis": r.get("nroChasis"),
        "nro_motor": r.get("nroMotor"),
        "pais": dig(r, "pais", "abrev"),
        "pais_desc": dig(r, "pais", "descripcion"),
        "tipo_vehiculo": dig(s, "tipoVehiculo", "descripcion") or dig(car, "tipoVehiculo", "descripcion"),
        "tipo_vehiculo_abrev": dig(s, "tipoVehiculo", "abrev") or dig(car, "tipoVehiculo", "abrev"),
        "cantidad_ejes": s.get("cantidadEjes") or chasis.get("cantEjes"),
        "marca": dig(s, "chasisMarca", "descripcion")
                 or dig(chasis, "chasisModelo", "chasisMarca", "descripcion"),
        "modelo": dig(s, "chasisModelo", "descripcion") or dig(chasis, "chasisModelo", "descripcion"),
        "tipo_carroceria": dig(s, "tipoCarroceria", "descripcion") or dig(car, "tipoCarroceria", "descripcion"),
        "carroceria_marca": dig(s, "carroceriaMarca", "descripcion") or dig(car, "carroceriaMarca", "descripcion"),
        "peso_vacio": dig(s, "vehiculoCargaDefault", "pesoVacio"),
        "carga_util": dig(s, "vehiculoCargaDefault", "cargaUtil"),
        "peso_maximo": dig(s, "vehiculoCargaDefault", "pesoMaximo"),
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
        done = failed = 0

        with OUTFILE.open("a", encoding="utf-8") as fh, DONEFILE.open("a", encoding="utf-8") as dfh:
            async def one(off: int) -> None:
                nonlocal done, failed
                try:
                    async with sem:
                        res, _ = await seop_page(cli, "parquesMoviles", off)
                except PageFailed:
                    async with lock:
                        failed += 1
                    return                      # not marked done -> next run retries it
                async with lock:
                    for r in res:
                        fh.write(json.dumps(flatten(r), ensure_ascii=False) + "\n")
                    dfh.write(f"{off}\n")
                    done += 1
                    if done % 200 == 0:
                        fh.flush()
                        dfh.flush()
                        print(f"[s3] {done}/{len(offsets)} pages this run | unresolved {failed}", flush=True)

            await asyncio.gather(*(one(o) for o in offsets))

    n = sum(1 for _ in OUTFILE.open(encoding="utf-8"))
    print(f"[s3] DONE rows={n} (target {total}) unresolved_pages={failed} -> {OUTFILE}", flush=True)
    if failed:
        print("[s3] re-run to fetch the unresolved pages", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
