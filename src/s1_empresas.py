"""Stage 1 - dump the CNRT company registry from the SEOP public API.

/v1/empresas is the authoritative list of operators registered with CNRT. It
carries the CUIT, the contact e-mail, the PAUT (international permit number) and
the tiposEmpresa flags that mark a company as a cargo carrier ("CA").
"""
from __future__ import annotations

import asyncio

from common import RAW, client, dig, dump_collection, read_jsonl

OUTFILE = RAW / "empresas.jsonl"
CONCURRENCY = 8


def flatten(r: dict) -> dict:
    tipos = [t.get("abrev") for t in (r.get("tiposEmpresa") or []) if t.get("abrev")]
    return {
        "empresa_id": r.get("id"),
        "razon_social": r.get("razonSocial"),
        "nombre_fantasia": r.get("nombreFantasia"),
        "tipo_documento": dig(r, "tipoDocumento", "abrev"),
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
        await dump_collection(cli, "empresas", flatten, OUTFILE,
                              concurrency=CONCURRENCY, label="s1")
    cargas = sum(1 for r in read_jsonl(OUTFILE) if r.get("es_cargas"))
    print(f"[s1] cargo-flagged companies: {cargas}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
