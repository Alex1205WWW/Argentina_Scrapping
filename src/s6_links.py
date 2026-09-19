"""Stage 6 - the plate <-> carrier link, for every cargo operator.

/v1/parquesMovilesOperadores joins a vehicle (parqueMovil, with its dominio and
SEMIRREMOLQUE / TRACTOR type) to the operator that runs it. fechaBaja and vigente
say whether that assignment is still live, which is what makes a plate "active"
on the CNRT side. Only cargo operators from stage 5 are swept.

Resumable: each finished operador id is appended to links.done.
"""
from __future__ import annotations

import asyncio
import json

from common import PAGE, RAW, PageFailed, client, seop_page

IN_OPERADORES = RAW / "operadores_cargas.jsonl"
OUTFILE = RAW / "links.jsonl"
DONEFILE = RAW / "links.done"
CONCURRENCY = 10


def _d(o, *path):
    for p in path:
        if not isinstance(o, dict):
            return None
        o = o.get(p)
    return o


def flatten(r: dict) -> dict:
    pm = r.get("parqueMovil") or {}
    s = pm.get("parqueMovilSimplificado") or {}
    car = pm.get("carroceria") or {}
    emp = _d(r, "operador", "empresa") or {}
    return {
        "link_id": r.get("id"),
        "operador_id": _d(r, "operador", "id"),
        "parque_movil_id": pm.get("id"),
        "dominio": (pm.get("dominio") or "").strip().upper(),
        "anio_modelo": pm.get("anioModelo"),
        "nro_chasis": pm.get("nroChasis"),
        "tipo_vehiculo": _d(s, "tipoVehiculo", "descripcion") or _d(car, "tipoVehiculo", "descripcion"),
        "cantidad_ejes": s.get("cantidadEjes"),
        "marca": _d(s, "chasisMarca", "descripcion"),
        "modelo": _d(s, "chasisModelo", "descripcion"),
        "tipo_carroceria": _d(s, "tipoCarroceria", "descripcion"),
        "peso_maximo": _d(s, "vehiculoCargaDefault", "pesoMaximo"),
        "carga_util": _d(s, "vehiculoCargaDefault", "cargaUtil"),
        "pais": _d(pm, "pais", "abrev"),
        "cuit": emp.get("nroDocumento"),
        "razon_social": emp.get("razonSocial"),
        "email": emp.get("email"),
        "paut": emp.get("paut"),
        "jurisdiccion": _d(r, "operador", "jurisdiccion", "abrev"),
        "interno": r.get("interno"),
        "fecha_alta": r.get("fechaAlta"),
        "fecha_baja": r.get("fechaBaja"),
        "baja_genuina": r.get("bajaGenuina"),
        "vigente": r.get("vigente"),
        "activo": r.get("fechaBaja") is None,
    }


def load_operadores() -> list[int]:
    ids = []
    with IN_OPERADORES.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ids.append(json.loads(line)["operador_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return sorted(set(ids))


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
                    # short read: store nothing rather than a truncated fleet
                    async with lock:
                        failed += 1
                    return
                async with lock:
                    for r in rows:
                        fh.write(json.dumps(flatten(r), ensure_ascii=False) + "\n")
                    dfh.write(str(op) + "\n")
                    processed += 1
                    links += len(rows)
                    if processed % 250 == 0:
                        fh.flush()
                        dfh.flush()
                        print(f"[s6] {processed}/{len(todo)} operadores | {links} links | reintentar {failed}", flush=True)

            await asyncio.gather(*(one(o) for o in todo))

    print(f"[s6] DONE operadores={processed} links={links} reintentar={failed} -> {OUTFILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
