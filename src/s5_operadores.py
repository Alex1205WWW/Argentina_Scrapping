"""Stage 5 - dump every CARGO operator registered with CNRT.

An "operador" is a company acting under a given transport type/jurisdiction.
tipoTransporte=1 is CARGAS AUTOMOTOR, so this is the freight-carrier universe:
each row carries the operating company with its CUIT, e-mail and PAUT, plus the
jurisdiction (JN national / JI international) the carrier is authorised for.
"""
from __future__ import annotations

import asyncio
import json

from common import PAGE, RAW, client, seop_page

OUTFILE = RAW / "operadores_cargas.jsonl"
CONCURRENCY = 12
TIPO_TRANSPORTE_CARGAS = 1


def _d(o, *path):
    for p in path:
        if not isinstance(o, dict):
            return None
        o = o.get(p)
    return o


def flatten(r: dict) -> dict:
    emp = r.get("empresa") or {}
    return {
        "operador_id": r.get("id"),
        "empresa_id": emp.get("id"),
        "razon_social": emp.get("razonSocial"),
        "nombre_fantasia": emp.get("nombreFantasia"),
        "tipo_documento": _d(emp, "tipoDocumento", "abrev"),
        "cuit": emp.get("nroDocumento"),
        "es_persona_fisica": emp.get("esPersonaFisica"),
        "paut": emp.get("paut"),
        "email": emp.get("email"),
        "fecha_inscripcion_cnrt": emp.get("fechaInscripcionCNRT"),
        "estado_empresa": emp.get("estadoEmpresa"),
        "pais_origen": emp.get("paisOrigen"),
        "tipos_empresa": [t.get("abrev") for t in (emp.get("tiposEmpresa") or [])],
        "jurisdiccion": _d(r, "jurisdiccion", "abrev"),
        "jurisdiccion_desc": _d(r, "jurisdiccion", "descripcion"),
        "internacional": _d(r, "jurisdiccion", "internacional"),
        "tipo_transporte_objeto": _d(r, "tipoTransporteObjeto", "descripcion"),
        "ambito": _d(r, "ambito", "descripcion"),
        "clase_modalidad": _d(r, "claseModalidad", "descripcion"),
        "provincia": _d(r, "provincia", "descripcion"),
        "municipio": _d(r, "municipio", "descripcion"),
        "origen": r.get("origen"),
        "destino": r.get("destino"),
        "localidad_origen": _d(r, "localidadOrigen", "descripcion"),
        "localidad_destino": _d(r, "localidadDestino", "descripcion"),
        "vigencia_desde": r.get("vigenciaDesde"),
        "vigencia_hasta": r.get("vigenciaHasta"),
        "vigente": r.get("vigente"),
    }


async def main() -> None:
    async with client(limit=CONCURRENCY, timeout=90.0) as cli:
        _, total = await seop_page(cli, "operadores", 0, limit=1,
                                   tipoTransporte=TIPO_TRANSPORTE_CARGAS)
        print(f"[s5] cargo operadores = {total}", flush=True)

        offsets = list(range(0, total, PAGE))
        sem = asyncio.Semaphore(CONCURRENCY)
        rows: dict[int, list] = {}

        async def one(off: int) -> None:
            async with sem:
                res, _ = await seop_page(cli, "operadores", off,
                                         tipoTransporte=TIPO_TRANSPORTE_CARGAS)
            rows[off] = res
            if len(rows) % 40 == 0:
                print(f"[s5] {len(rows)}/{len(offsets)} pages", flush=True)

        await asyncio.gather(*(one(o) for o in offsets))

    seen = set()
    with OUTFILE.open("w", encoding="utf-8") as fh:
        for off in sorted(rows):
            for r in rows[off]:
                if r.get("id") in seen:
                    continue
                seen.add(r.get("id"))
                fh.write(json.dumps(flatten(r), ensure_ascii=False) + "\n")

    print(f"[s5] DONE operadores={len(seen)} (expected {total}) -> {OUTFILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
