"""Stage 9 - assemble every scraped source into the freight database.

Loads the JSONL dumps into SQLite, joins them against the ARCA padron already
loaded by stage 4, and derives the analysis views the UI and the CSV export read.

Safe to run against a partial scrape: it rebuilds from whatever dumps exist.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from common import OUT, RAW

DB = OUT / "freight.db"

# Cargo vehicle types as CNRT spells them (accents included).
CARGO_TYPES = (
    "SEMIRREMOLQUE", "TRACTOR", "CAMION", "CAMIÓN", "ACOPLADO",
    "BATEA", "CARRETON", "CARRETÓN",
)
SEMI_TYPE = "SEMIRREMOLQUE"


def load_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def norm(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    return v


def table(con, name, cols, rows):
    coldef = ", ".join(f'"{c}"' for c in cols)
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} ({coldef})")
    ph = ",".join("?" * len(cols))
    con.executemany(f"INSERT INTO {name} VALUES ({ph})", rows)
    con.commit()
    n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"[s9] {name:<26} {n:>9,} rows", flush=True)
    return n


def main() -> None:
    con = sqlite3.connect(DB)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")

    # ---- CNRT company registry -----------------------------------------
    cols = ["empresa_id", "razon_social", "nombre_fantasia", "tipo_documento", "cuit",
            "es_persona_fisica", "paut", "email", "fecha_inscripcion_cnrt", "estado_empresa",
            "vigencia_desde", "vigencia_hasta", "pais_origen", "tipos_empresa", "es_cargas",
            "observacion"]
    table(con, "empresas", cols,
          ([norm(r.get(c)) for c in cols] for r in load_jsonl(RAW / "empresas.jsonl")))

    # ---- cargo operators -------------------------------------------------
    cols = ["operador_id", "empresa_id", "razon_social", "nombre_fantasia", "tipo_documento",
            "cuit", "es_persona_fisica", "paut", "email", "fecha_inscripcion_cnrt",
            "estado_empresa", "pais_origen", "tipos_empresa", "jurisdiccion",
            "jurisdiccion_desc", "internacional", "tipo_transporte_objeto", "ambito",
            "clase_modalidad", "provincia", "municipio", "origen", "destino",
            "localidad_origen", "localidad_destino", "vigencia_desde", "vigencia_hasta",
            "vigente"]
    table(con, "operadores_cargas", cols,
          ([norm(r.get(c)) for c in cols] for r in load_jsonl(RAW / "operadores_cargas.jsonl")))

    # ---- full CNRT vehicle registry --------------------------------------
    cols = ["parque_movil_id", "dominio", "anio_modelo", "nro_chasis", "nro_motor", "pais",
            "pais_desc", "tipo_vehiculo", "tipo_vehiculo_abrev", "cantidad_ejes", "marca",
            "modelo", "tipo_carroceria", "carroceria_marca", "peso_vacio", "carga_util",
            "peso_maximo", "cant_asientos"]
    table(con, "parque_movil", cols,
          ([norm(r.get(c)) for c in cols] for r in load_jsonl(RAW / "parque_movil.jsonl")))
    con.execute("CREATE INDEX IF NOT EXISTS ix_pm_dom ON parque_movil(dominio)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pm_tipo ON parque_movil(tipo_vehiculo, pais)")

    # ---- plate <-> carrier links -----------------------------------------
    # link_id is unique per assignment; the dump can hold repeats because stage 6
    # appends and a resumed run may re-emit rows whose done-marker was not yet
    # flushed. Deduplicate here so downstream counts are not inflated.
    cols = ["link_id", "operador_id", "parque_movil_id", "dominio", "anio_modelo",
            "nro_chasis", "tipo_vehiculo", "cantidad_ejes", "marca", "modelo",
            "tipo_carroceria", "peso_maximo", "carga_util", "pais", "cuit", "razon_social",
            "email", "paut", "jurisdiccion", "interno", "fecha_alta", "fecha_baja",
            "baja_genuina", "vigente", "activo"]

    def dedup_links():
        seen = set()
        for r in load_jsonl(RAW / "links.jsonl"):
            lid = r.get("link_id")
            if lid in seen:
                continue
            seen.add(lid)
            yield [norm(r.get(c)) for c in cols]

    table(con, "links", cols, dedup_links())
    con.execute("CREATE INDEX IF NOT EXISTS ix_lk_dom ON links(dominio)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_lk_cuit ON links(cuit)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_lk_tipo ON links(tipo_vehiculo, activo)")

    # ---- international fleet + MERCOSUR permits ---------------------------
    veh_rows, permit_rows = [], []
    for r in load_jsonl(RAW / "flota.jsonl"):
        if r.get("_miss"):
            continue
        for v in r.get("vehiculos", []):
            dom = (v.get("dominio") or "").strip().upper()
            veh_rows.append([
                dom, v.get("anio_modelo"), v.get("empresa_nro"), v.get("paut"), v.get("pais"),
                v.get("nro_chasis"), v.get("cantidad_ejes"), v.get("tipo_vehiculo"),
                v.get("chasis_marca"), v.get("tipo_carroceria"), v.get("razon_social"),
                v.get("tipo_documento_abrev"), v.get("nro_documento"),
            ])
            for p in (v.get("permisos") or []):
                permit_rows.append([dom, v.get("nro_documento"), p.get("origen"),
                                    p.get("transito"), p.get("destino"),
                                    p.get("vigenciaHasta")])
    table(con, "flota_internacional",
          ["dominio", "anio_modelo", "empresa_nro", "paut", "pais", "nro_chasis",
           "cantidad_ejes", "tipo_vehiculo", "chasis_marca", "tipo_carroceria",
           "razon_social", "tipo_documento", "cuit"], veh_rows)
    table(con, "permisos_internacionales",
          ["dominio", "cuit", "origen", "transito", "destino", "vigencia_hasta"], permit_rows)
    con.execute("CREATE INDEX IF NOT EXISTS ix_fi_dom ON flota_internacional(dominio)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_fi_cuit ON flota_internacional(cuit)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_pi_dom ON permisos_internacionales(dominio)")

    # ---- RUTA constancia per plate ----------------------------------------
    cols = ["dominio", "ruta_vigente", "nro_constancia", "nro_certificado",
            "serie_certificado", "provisoria", "fecha_alta", "fecha_validacion"]
    table(con, "ruta", cols,
          ([norm(r.get(c)) for c in cols] for r in load_jsonl(RAW / "ruta.jsonl")))
    con.execute("CREATE INDEX IF NOT EXISTS ix_ruta_dom ON ruta(dominio)")
    con.commit()

    # ---- resolve exactly one owner per plate --------------------------------
    # A carrier often holds several operating licences and the same vehicle is
    # attached to each, so a plate can carry several live links that all name the
    # same CUIT. Collapse them to the most recent one, otherwise every join
    # multiplies the plate.
    print("[s9] resolving plate owners ...", flush=True)
    con.executescript("""
        DROP TABLE IF EXISTS plate_owner;
        CREATE TABLE plate_owner AS
        WITH live AS (
            SELECT * FROM links
            WHERE activo = 1 AND cuit IS NOT NULL AND cuit <> ''
        ),
        agg AS (
            SELECT dominio, COUNT(*) AS n_links, COUNT(DISTINCT cuit) AS n_cuits
            FROM live GROUP BY dominio
        ),
        ranked AS (
            SELECT l.*, ROW_NUMBER() OVER (PARTITION BY l.dominio
                                           ORDER BY l.fecha_alta DESC,
                                                    l.link_id DESC) AS rn
            FROM live l
        )
        SELECT r.dominio, r.cuit, r.razon_social, r.email, r.paut, r.jurisdiccion,
               r.fecha_alta, r.fecha_baja, r.operador_id, a.n_links, a.n_cuits
        FROM ranked r JOIN agg a ON a.dominio = r.dominio
        WHERE r.rn = 1;
        CREATE UNIQUE INDEX ix_po_dom ON plate_owner(dominio);
        CREATE INDEX ix_po_cuit ON plate_owner(cuit);
    """)
    con.commit()
    print(f"[s9] {'plate_owner':<26} "
          f"{con.execute('SELECT COUNT(*) FROM plate_owner').fetchone()[0]:>9,} rows")

    # ---- derived view: one row per Argentine cargo plate -------------------
    print("[s9] building derived view v_vehiculos_carga ...", flush=True)
    types_sql = ",".join("'" + t.replace("'", "''") + "'" for t in CARGO_TYPES)
    con.executescript(f"""
        DROP VIEW IF EXISTS v_vehiculos_carga;
        CREATE VIEW v_vehiculos_carga AS
        SELECT
            pm.dominio,
            pm.tipo_vehiculo,
            pm.anio_modelo,
            pm.marca,
            pm.modelo,
            pm.tipo_carroceria,
            pm.cantidad_ejes,
            pm.nro_chasis,
            pm.peso_maximo,
            pm.carga_util,
            pm.pais,
            l.cuit,
            l.razon_social,
            l.email,
            l.paut,
            l.jurisdiccion,
            l.fecha_alta            AS link_fecha_alta,
            l.fecha_baja            AS link_fecha_baja,
            CASE WHEN l.dominio IS NULL THEN 0 ELSE 1 END AS link_activo,
            l.n_links, l.n_cuits,
            r.ruta_vigente,
            r.nro_constancia        AS ruta_constancia,
            r.nro_certificado       AS ruta_certificado,
            r.fecha_alta            AS ruta_fecha_alta,
            CASE WHEN a.cuit IS NOT NULL THEN 1 ELSE 0 END AS cuit_activo_arca,
            a.denominacion          AS arca_denominacion,
            a.imp_iva, a.imp_ganancias, a.empleador,
            -- a real Argentine plate is either the pre-2016 AAA999 form or the
            -- MERCOSUR AA999AA form; CNRT also stores placeholders ("*G39943")
            -- and malformed legacy strings, none of which hold a live RUTA
            CASE WHEN pm.dominio GLOB '[A-Z][A-Z][A-Z][0-9][0-9][0-9]'
                   OR pm.dominio GLOB '[A-Z][A-Z][0-9][0-9][0-9][A-Z][A-Z]'
                 THEN 1 ELSE 0 END AS dominio_valido
        FROM (
            -- a handful of plates appear twice (re-registration); keep the newest
            SELECT * FROM parque_movil
            WHERE parque_movil_id IN (
                SELECT MAX(CAST(parque_movil_id AS INTEGER))
                FROM parque_movil WHERE pais='AR' GROUP BY dominio)
        ) pm
        LEFT JOIN plate_owner l ON l.dominio = pm.dominio
        LEFT JOIN ruta  r ON r.dominio = pm.dominio
        LEFT JOIN arca_padron a ON a.cuit = l.cuit
        WHERE pm.pais = 'AR' AND pm.tipo_vehiculo IN ({types_sql});
    """)
    con.commit()

    checks = [
        ("parque_movil rows", "SELECT COUNT(*) FROM parque_movil"),
        ("  AR plates", "SELECT COUNT(DISTINCT dominio) FROM parque_movil WHERE pais='AR'"),
        ("  AR SEMIRREMOLQUE",
         "SELECT COUNT(DISTINCT dominio) FROM parque_movil WHERE pais='AR' AND tipo_vehiculo='SEMIRREMOLQUE'"),
        ("  ...dominio valido",
         "SELECT COUNT(*) FROM v_vehiculos_carga WHERE tipo_vehiculo='SEMIRREMOLQUE' AND dominio_valido=1"),
        ("  AR TRACTOR",
         "SELECT COUNT(DISTINCT dominio) FROM parque_movil WHERE pais='AR' AND tipo_vehiculo='TRACTOR'"),
        ("links rows", "SELECT COUNT(*) FROM links"),
        ("  links activos", "SELECT COUNT(*) FROM links WHERE activo=1"),
        ("  distinct CUIT", "SELECT COUNT(DISTINCT cuit) FROM links WHERE cuit IS NOT NULL AND cuit<>''"),
        ("flota_internacional", "SELECT COUNT(DISTINCT dominio) FROM flota_internacional"),
    ]
    print()
    for label, sql in checks:
        print(f"[s9]   {label:<26} {con.execute(sql).fetchone()[0]:>9,}")

    con.close()
    print(f"\n[s9] DONE -> {DB}")


if __name__ == "__main__":
    main()
