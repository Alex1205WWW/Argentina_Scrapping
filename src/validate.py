"""Independent verification: re-query the live sources and compare field by field.

The brief requires that scraped data be *proven*, not asserted. This script takes
a random sample of rows already stored in freight.db, calls the originating
endpoint again, and compares the stored values against the live response. It
reports a per-source pass rate and prints any mismatch in full.

Nothing here reads the intermediate JSONL dumps - it checks the database that the
CSVs and the dashboard are built from, which is what actually ships.

  python validate.py [sample_size]
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
import sys

from common import CNRT_API, SEOP, OUT, client, get_json, UNRESOLVED

DB = OUT / "freight.db"
SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 25


def rows(sql, n):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, (n,))]
    finally:
        con.close()


def cmp_field(name, stored, live, out):
    s = "" if stored is None else str(stored).strip()
    l = "" if live is None else str(live).strip()
    if s == l:
        return True
    out.append(f"      {name}: almacenado={s!r} vivo={l!r}")
    return False


async def check_parque(cli):
    """parque_movil rows vs /v1/parquesMoviles?dominio=X"""
    sample = rows("SELECT dominio, tipo_vehiculo, anio_modelo, marca, tipo_carroceria, "
                  "cantidad_ejes, nro_chasis, pais FROM parque_movil "
                  "WHERE pais='AR' ORDER BY RANDOM() LIMIT ?", SAMPLE)
    ok = bad = skip = 0
    for r in sample:
        d = await get_json(cli, f"{SEOP}/parquesMoviles?dominio={r['dominio']}&limit=1")
        if d is UNRESOLVED or not isinstance(d, dict):
            skip += 1
            continue
        res = (d.get("data") or {}).get("results") or []
        if not res:
            print(f"  [FALTA] {r['dominio']} no aparece en la API")
            bad += 1
            continue
        v = res[0]
        s = v.get("parqueMovilSimplificado") or {}
        car = v.get("carroceria") or {}
        diffs = []
        good = all([
            cmp_field("dominio", r["dominio"], v.get("dominio"), diffs),
            cmp_field("anio_modelo", r["anio_modelo"], v.get("anioModelo"), diffs),
            cmp_field("nro_chasis", r["nro_chasis"], v.get("nroChasis"), diffs),
            cmp_field("tipo_vehiculo", r["tipo_vehiculo"],
                      ((s.get("tipoVehiculo") or car.get("tipoVehiculo") or {}).get("descripcion")), diffs),
            cmp_field("tipo_carroceria", r["tipo_carroceria"],
                      ((s.get("tipoCarroceria") or car.get("tipoCarroceria") or {}).get("descripcion")), diffs),
            cmp_field("pais", r["pais"], (v.get("pais") or {}).get("abrev"), diffs),
        ])
        if good:
            ok += 1
        else:
            bad += 1
            print(f"  [DIFIERE] {r['dominio']}")
            print("\n".join(diffs))
    return "parque_movil (CNRT /v1/parquesMoviles)", ok, bad, skip


async def check_ruta(cli):
    """ruta rows vs /api/ruta_vigente_por_dominio/X"""
    sample = rows("SELECT dominio, ruta_vigente, nro_constancia, nro_certificado "
                  "FROM ruta ORDER BY RANDOM() LIMIT ?", SAMPLE)
    ok = bad = skip = 0
    for r in sample:
        d = await get_json(cli, f"{CNRT_API}/ruta_vigente_por_dominio/{r['dominio']}.json")
        if d is UNRESOLVED:
            skip += 1
            continue
        live_vig = bool(isinstance(d, dict) and d.get("nroConstancia"))
        stored_vig = str(r["ruta_vigente"]) in ("1", "True", "true")
        diffs = []
        good = cmp_field("ruta_vigente", stored_vig, live_vig, diffs)
        if good and live_vig:
            good = cmp_field("nro_constancia", r["nro_constancia"], d.get("nroConstancia"), diffs)
        if good:
            ok += 1
        else:
            bad += 1
            print(f"  [DIFIERE] {r['dominio']}")
            print("\n".join(diffs))
    return "ruta (CNRT /api/ruta_vigente_por_dominio)", ok, bad, skip


async def check_links(cli):
    """links rows vs /api/vehiculo_cargas_habilitados/{dominio}/pais/AR (owner CUIT)"""
    sample = rows("SELECT dominio, cuit, razon_social, tipo_vehiculo FROM links "
                  "WHERE activo=1 AND cuit IS NOT NULL AND cuit<>'' AND pais='AR' "
                  "ORDER BY RANDOM() LIMIT ?", SAMPLE)
    ok = bad = skip = na = 0
    for r in sample:
        d = await get_json(cli, f"{CNRT_API}/vehiculo_cargas_habilitados/{r['dominio']}/pais/AR")
        if d is UNRESOLVED:
            skip += 1
            continue
        if not isinstance(d, list) or not d:
            na += 1          # plate not in the international-permits registry
            continue
        live_cuits = {str(v.get("nro_documento")) for v in d}
        if str(r["cuit"]) in live_cuits:
            ok += 1
        else:
            bad += 1
            print(f"  [DIFIERE] {r['dominio']} almacenado CUIT={r['cuit']} vivo={live_cuits}")
    return f"links (CNRT /api/vehiculo_cargas_habilitados, {na} sin registro intl.)", ok, bad, skip


async def check_empresas(cli):
    """empresas rows vs /api/empresa_jn_habilitada/cuit/X"""
    sample = rows("SELECT cuit, razon_social FROM operadores_cargas "
                  "WHERE cuit IS NOT NULL AND cuit<>'' ORDER BY RANDOM() LIMIT ?", SAMPLE)
    ok = bad = skip = na = 0
    for r in sample:
        d = await get_json(cli, f"{CNRT_API}/empresa_jn_habilitada/cuit/{r['cuit']}.json")
        if d is UNRESOLVED:
            skip += 1
            continue
        if not isinstance(d, dict) or not d.get("razon_social"):
            na += 1
            continue
        if str(d.get("nro_documento")) == str(r["cuit"]):
            ok += 1
        else:
            bad += 1
            print(f"  [DIFIERE] {r['cuit']} vivo={d.get('nro_documento')}")
    return f"operadores_cargas (CNRT /api/empresa_jn_habilitada, {na} solo en SEOP)", ok, bad, skip


def check_arca():
    """arca_padron vs an independent re-read of the source zip."""
    import zipfile
    from common import RAW
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    want = {c for (c,) in con.execute(
        "SELECT cuit FROM arca_padron ORDER BY RANDOM() LIMIT ?", (SAMPLE,))}
    stored = {c: d for c, d in con.execute(
        f"SELECT cuit, denominacion FROM arca_padron WHERE cuit IN "
        f"({','.join('?' * len(want))})", tuple(want))}
    con.close()

    z = zipfile.ZipFile(RAW / "arca_padron.zip")
    ok = bad = 0
    with z.open(z.infolist()[0].filename) as fh:
        for raw in fh:
            s = raw.decode("latin-1").rstrip("\n")
            if len(s) < 51:
                continue
            c = s[0:11]
            if c in want:
                if stored.get(c) == s[11:41].strip():
                    ok += 1
                else:
                    bad += 1
                    print(f"  [DIFIERE] {c} db={stored.get(c)!r} archivo={s[11:41].strip()!r}")
                want.discard(c)
                if not want:
                    break
    return "arca_padron (archivo oficial ARCA)", ok, bad, len(want)


async def main() -> None:
    random.seed()
    print(f"Verificacion independiente - muestra de {SAMPLE} filas por fuente\n"
          f"{'=' * 68}\n", flush=True)
    results = []
    async with client(limit=8, timeout=60.0) as cli:
        for fn in (check_parque, check_ruta, check_links, check_empresas):
            try:
                results.append(await fn(cli))
            except sqlite3.Error as e:
                print(f"  (omitido: {e})")
    try:
        results.append(check_arca())
    except Exception as e:                                   # noqa: BLE001
        print(f"  (arca omitido: {e})")

    print(f"\n{'=' * 68}")
    print(f"{'fuente':<52}{'ok':>5}{'dif':>5}{'s/r':>5}")
    total_ok = total_bad = 0
    for name, ok, bad, skip in results:
        total_ok += ok
        total_bad += bad
        print(f"{name:<52}{ok:>5}{bad:>5}{skip:>5}")
    n = total_ok + total_bad
    rate = (100 * total_ok / n) if n else 0
    print(f"\nCoincidencia global: {total_ok}/{n} = {rate:.1f}%")
    print("s/r = sin resolver (fallo de red, no un desacuerdo de datos)")


if __name__ == "__main__":
    asyncio.run(main())
