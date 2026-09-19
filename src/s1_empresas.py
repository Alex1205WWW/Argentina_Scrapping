"""Stage 1 - dump the CNRT company registry from the SEOP public API.

/v1/empresas is the authoritative list of operators registered with CNRT. It
carries the CUIT, the contact e-mail, the PAUT (international permit number) and
the tiposEmpresa flags that mark a company as a cargo carrier ("CA").
"""
from __future__ import annotations

import asyncio
import json

from common import PAGE, RAW, client, seop_page

OUTFILE = RAW / "empresas.jsonl"
CONCURRENCY = 8


def flatten(r: dict) -> dict:
    tipos = [t.get("abrev") for t in (r.get("tiposEmpresa") or []) if t.get("abrev")]
    return {
        "empresa_id": r.get("id"),
        "razon_social": r.get("razonSocial"),
        "nombre_fantasia": r.get("nombreFantasia"),
        "tipo_documento": (r.get("tipoDocumento") or {}).get("abrev"),
        "cuit": r.get("nroDocumento"),
        "es_persona_fisica": r.get("esPersonaFisica"),
        "paut": r.get("paut"),
        "email": r.get("email"),
        "fecha_inscripcion_cnrt": r.get("fechaInscripcionCNRT"),
        "estado_empresa": r.get("estadoEmpresa"),
        "vigencia_desde": r.get("vigenciaDesde"),
        "vigencia_hasta": r.get("vigenciaHasta"),
        "pais_origen": r.get("paisOrigen"),
        "tipos_empresa": tipos,
        "es_cargas": "CA" in tipos,
        "observacion": r.get("observacion"),
    }


async def main() -> None:
    async with client(limit=CONCURRENCY) as cli:
        first, total = await seop_page(cli, "empresas", 0)
        print(f"[s1] total empresas = {total}", flush=True)

        offsets = list(range(0, total, PAGE))
        sem = asyncio.Semaphore(CONCURRENCY)
        rows: dict[int, list] = {}

        async def one(off: int) -> None:
            async with sem:
                res, _ = await seop_page(cli, "empresas", off)
            rows[off] = res
            if len(rows) % 50 == 0:
                print(f"[s1] {len(rows)}/{len(offsets)} pages", flush=True)

        await asyncio.gather(*(one(o) for o in offsets))

    seen, n_cargas = set(), 0
    with OUTFILE.open("w", encoding="utf-8") as fh:
        for off in sorted(rows):
            for r in rows[off]:
                if r.get("id") in seen:
                    continue
                seen.add(r.get("id"))
                flat = flatten(r)
                n_cargas += bool(flat["es_cargas"])
                fh.write(json.dumps(flat, ensure_ascii=False) + "\n")

    print(f"[s1] DONE empresas={len(seen)} (expected {total}) cargas={n_cargas} -> {OUTFILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
