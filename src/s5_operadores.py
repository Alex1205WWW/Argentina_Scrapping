"""Stage 5 - dump every CARGO operator registered with CNRT.

An "operador" is a company acting under a given transport type/jurisdiction.
tipoTransporte=1 is CARGAS AUTOMOTOR, so this is the freight-carrier universe:
each row carries the operating company with its CUIT, e-mail and PAUT, plus the
jurisdiction (JN national / JI international) the carrier is authorised for.
"""
from __future__ import annotations

import asyncio

from common import RAW, client, dig, dump_collection

OUTFILE = RAW / "operadores_cargas.jsonl"
CONCURRENCY = 12
TIPO_TRANSPORTE_CARGAS = 1


def flatten(r: dict) -> dict:
    emp = r.get("empresa") or {}
    return {
        "operador_id": r.get("id"),
        "empresa_id": emp.get("id"),
        "razon_social": emp.get("razonSocial"),
        "nombre_fantasia": emp.get("nombreFantasia"),
        "tipo_documento": dig(emp, "tipoDocumento", "abrev"),
        "cuit": emp.get("nroDocumento"),
        "es_persona_fisica": emp.get("esPersonaFisica"),
        "paut": emp.get("paut"),
        "email": emp.get("email"),
        "fecha_inscripcion_cnrt": emp.get("fechaInscripcionCNRT"),
        "estado_empresa": emp.get("estadoEmpresa"),
        "pais_origen": emp.get("paisOrigen"),
        "tipos_empresa": [t.get("abrev") for t in (emp.get("tiposEmpresa") or [])],
        "jurisdiccion": dig(r, "jurisdiccion", "abrev"),
        "jurisdiccion_desc": dig(r, "jurisdiccion", "descripcion"),
        "internacional": dig(r, "jurisdiccion", "internacional"),
        "tipo_transporte_objeto": dig(r, "tipoTransporteObjeto", "descripcion"),
        "ambito": dig(r, "ambito", "descripcion"),
        "clase_modalidad": dig(r, "claseModalidad", "descripcion"),
        "provincia": dig(r, "provincia", "descripcion"),
        "municipio": dig(r, "municipio", "descripcion"),
        "origen": r.get("origen"),
        "destino": r.get("destino"),
        "localidad_origen": dig(r, "localidadOrigen", "descripcion"),
        "localidad_destino": dig(r, "localidadDestino", "descripcion"),
        "vigencia_desde": r.get("vigenciaDesde"),
        "vigencia_hasta": r.get("vigenciaHasta"),
        "vigente": r.get("vigente"),
    }


async def main() -> None:
    async with client(limit=CONCURRENCY, timeout=90.0) as cli:
        await dump_collection(cli, "operadores", flatten, OUTFILE,
                              concurrency=CONCURRENCY, label="s5",
                              tipoTransporte=TIPO_TRANSPORTE_CARGAS)


if __name__ == "__main__":
    asyncio.run(main())
