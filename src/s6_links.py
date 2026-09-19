"""Stage 6 - the plate <-> carrier link, for every cargo operator.

/v1/parquesMovilesOperadores joins a vehicle (parqueMovil, with its dominio and
SEMIRREMOLQUE / TRACTOR type) to the operator that runs it. fechaBaja and vigente
say whether that assignment is still live, which is what makes a plate "active"
on the CNRT side. Only cargo operators from stage 5 are swept.

Resumable: each finished operador id is appended to links.done. An operator whose
pages did not all settle is stored as nothing at all (never a truncated fleet)
and is retried on the next run.
"""
from __future__ import annotations

import asyncio
import json

from common import PAGE, RAW, PageFailed, client, dig, read_jsonl, seop_page

IN_OPERADORES = RAW / "operadores_cargas.jsonl"
OUTFILE = RAW / "links.jsonl"
DONEFILE = RAW / "links.done"
CONCURRENCY = 10


def flatten(r: dict) -> dict:
    pm = r.get("parqueMovil") or {}
    s = pm.get("parqueMovilSimplificado") or {}
    car = pm.get("carroceria") or {}
    emp = dig(r, "operador", "empresa") or {}
    return {
        "link_id": r.get("id"),
        "operador_id": dig(r, "operador", "id"),
        "parque_movil_id": pm.get("id"),
        "dominio": (pm.get("dominio") or "").strip().upper(),
        "anio_modelo": pm.get("anioModelo"),
        "nro_chasis": pm.get("nroChasis"),
        "tipo_vehiculo": dig(s, "tipoVehiculo", "descripcion") or dig(car, "tipoVehiculo", "descripcion"),
        "cantidad_ejes": s.get("cantidadEjes"),
        "marca": dig(s, "chasisMarca", "descripcion"),
        "modelo": dig(s, "chasisModelo", "descripcion"),
        "tipo_carroceria": dig(s, "tipoCarroceria", "descripcion"),
        "peso_maximo": dig(s, "vehiculoCargaDefault", "pesoMaximo"),
        "carga_util": dig(s, "vehiculoCargaDefault", "cargaUtil"),
        "pais": dig(pm, "pais", "abrev"),
        "cuit": emp.get("nroDocumento"),
        "razon_social": emp.get("razonSocial"),
        "email": emp.get("email"),
        "paut": emp.get("paut"),
        "jurisdiccion": dig(r, "operador", "jurisdiccion", "abrev"),
        "interno": r.get("interno"),
        "fecha_alta": r.get("fechaAlta"),
        "fecha_baja": r.get("fechaBaja"),
        "baja_genuina": r.get("bajaGenuina"),
        "vigente": r.get("vigente"),
        "activo": r.get("fechaBaja") is None,
    }


def load_operadores() -> list[int]:
    return sorted({r["operador_id"] for r in read_jsonl(IN_OPERADORES) if "operador_id" in r})


async def main() -> None:
    ops = load_operadores()
    done: set[int] = set()
    if DONEFILE.exists():
        done = {int(x) for x in DONEFILE.read_text().split() if x.strip()}
    todo = [o for o in ops if o not in done]
    print(f"[s6] cargo operadores {len(ops)} | done {len(done)} | todo {len(todo)}", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()
    processed = links = failed = 0

    async with client(limit=CONCURRENCY, timeout=120.0) as cli:
        with OUTFILE.open("a", encoding="utf-8") as fh, DONEFILE.open("a", encoding="utf-8") as dfh:
            async def one(op: int) -> None:
                nonlocal processed, links, failed
                rows, off, expected = [], 0, None
                try:
                    while True:
                        async with sem:
                            res, total = await seop_page(cli, "parquesMovilesOperadores",
                                                         off, operador=op)
                        if expected is None:
                            expected = total
                        rows.extend(res)
                        off += PAGE
                        if off >= total or not res:
                            break
                except PageFailed:
                    async with lock:
                        failed += 1
                    return  # not marked done - a resume retries this operator
                if expected and len(rows) < expected:
                    async with lock:            # short read: store nothing
                        failed += 1
                    return
                async with lock:
                    for r in rows:
                        fh.write(json.dumps(flatten(r), ensure_ascii=False) + "\n")
                    dfh.write(f"{op}\n")
                    processed += 1
                    links += len(rows)
                    if processed % 250 == 0:
                        fh.flush()
                        dfh.flush()
                        print(f"[s6] {processed}/{len(todo)} operadores | {links} links | retry {failed}", flush=True)

            await asyncio.gather(*(one(o) for o in todo))

    print(f"[s6] DONE operadores={processed} links={links} retry={failed} -> {OUTFILE}", flush=True)
    if failed:
        print("[s6] re-run to fetch the operators that did not settle", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
