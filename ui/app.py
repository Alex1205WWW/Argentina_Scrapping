"""Read-only dashboard over the Argentine freight-transport database.

Run:  .venv\\Scripts\\python.exe -m uvicorn app:app --app-dir ui --port 8000
Then: http://127.0.0.1:8000
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "out" / "freight.db"
HERE = Path(__file__).resolve().parent

app = FastAPI(title="Base de Datos de Transporte de Cargas - Argentina")


def q(sql: str, params: tuple = ()) -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


def one(sql: str, params: tuple = ()):
    r = q(sql, params)
    return list(r[0].values())[0] if r else 0


def has_rows(tbl: str) -> bool:
    try:
        return one(f"SELECT COUNT(*) FROM {tbl}") > 0
    except sqlite3.Error:
        return False


# The headline aggregates scan 6M-row tables; compute them once per database
# build (keyed on the file's mtime) instead of on every page load.
_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, fn):
    mtime = DB.stat().st_mtime if DB.exists() else 0.0
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    val = fn()
    _cache[key] = (mtime, val)
    return val


# --------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.get("/api/stats")
def stats():
    return cached("stats", _stats)


@app.get("/api/charts")
def charts():
    return cached("charts", _charts)


@app.get("/api/provenance")
def provenance():
    return cached("provenance", _provenance)


def _stats():
    # The headline set is the same one FINDINGS.md reports: Argentine semi-trailers
    # whose plate matches a real format, one row per plate, with the resolved
    # owner. All of it comes from v_vehiculos_carga so the UI and the report
    # can never disagree.
    SEMI = ("FROM v_vehiculos_carga WHERE tipo_vehiculo='SEMIRREMOLQUE' "
            "AND pais='AR' AND dominio_valido=1")
    semi_raw = one("SELECT COUNT(DISTINCT dominio) FROM parque_movil "
                   "WHERE pais='AR' AND tipo_vehiculo='SEMIRREMOLQUE'")
    semi_total = one(f"SELECT COUNT(*) {SEMI}")
    tract_total = one("SELECT COUNT(DISTINCT dominio) FROM parque_movil "
                      "WHERE pais='AR' AND tipo_vehiculo='TRACTOR'")

    ruta_ready = has_rows("ruta")
    semi_ruta = one(f"SELECT COUNT(*) {SEMI} AND ruta_vigente IN (1,'1','True')") \
        if ruta_ready else None
    semi_ruta_checked = one(f"SELECT COUNT(*) {SEMI} AND ruta_vigente IS NOT NULL") \
        if ruta_ready else 0

    semi_con_titular = one(f"SELECT COUNT(*) {SEMI} AND cuit IS NOT NULL AND cuit<>''")
    cuits_semi = one(f"SELECT COUNT(DISTINCT cuit) {SEMI} AND cuit IS NOT NULL AND cuit<>''")
    cuits_semi_arca = one(f"SELECT COUNT(DISTINCT cuit) {SEMI} AND cuit IS NOT NULL "
                          "AND cuit<>'' AND cuit_activo_arca=1")

    return {
        "semirremolques_ar": semi_total,
        "semirremolques_invalidos": semi_raw - semi_total,
        "tractores_ar": tract_total,
        "semirremolques_ruta_vigente": semi_ruta,
        "semirremolques_ruta_consultados": semi_ruta_checked,
        "semirremolques_con_titular": semi_con_titular,
        "cuits_titulares_semi": cuits_semi,
        "cuits_titulares_semi_activos_arca": cuits_semi_arca,
        "parque_total": one("SELECT COUNT(*) FROM parque_movil"),
        "parque_ar": one("SELECT COUNT(DISTINCT dominio) FROM parque_movil WHERE pais='AR'"),
        "empresas_cnrt": one("SELECT COUNT(*) FROM empresas"),
        "operadores_cargas": one("SELECT COUNT(*) FROM operadores_cargas"),
        "cuits_cargas": one("SELECT COUNT(DISTINCT cuit) FROM operadores_cargas "
                            "WHERE cuit IS NOT NULL AND cuit<>''"),
        "arca_padron": one("SELECT COUNT(*) FROM arca_padron"),
        "links": one("SELECT COUNT(*) FROM links"),
        "ruta_consultados": one("SELECT COUNT(*) FROM ruta") if ruta_ready else 0,
        "emails": one("SELECT COUNT(DISTINCT o.cuit) FROM operadores_cargas o "
                      "LEFT JOIN empresas e ON e.cuit = o.cuit "
                      "WHERE COALESCE(NULLIF(o.email,''), NULLIF(e.email,'')) IS NOT NULL"),
        "permisos": one("SELECT COUNT(*) FROM permisos_internacionales"),
    }


def _charts():
    tipos = q("SELECT tipo_vehiculo AS label, COUNT(DISTINCT dominio) AS value "
              "FROM parque_movil WHERE pais='AR' AND tipo_vehiculo IN "
              "('SEMIRREMOLQUE','TRACTOR','CAMION','CAMIÓN','ACOPLADO','BATEA',"
              "'CARRETON','CARRETÓN','CAMIONETA') "
              "GROUP BY tipo_vehiculo ORDER BY value DESC LIMIT 12")

    carroceria = q("SELECT COALESCE(tipo_carroceria,'SIN DATO') AS label, "
                   "COUNT(DISTINCT dominio) AS value FROM parque_movil "
                   "WHERE pais='AR' AND tipo_vehiculo='SEMIRREMOLQUE' "
                   "GROUP BY 1 ORDER BY value DESC LIMIT 10")

    anios = q("SELECT CAST(anio_modelo AS INTEGER) AS label, "
              "COUNT(DISTINCT dominio) AS value FROM parque_movil "
              "WHERE pais='AR' AND tipo_vehiculo='SEMIRREMOLQUE' "
              "AND anio_modelo IS NOT NULL AND CAST(anio_modelo AS INTEGER) BETWEEN 1960 AND 2026 "
              "GROUP BY 1 ORDER BY 1")

    paises = q("SELECT pais AS label, COUNT(DISTINCT dominio) AS value "
               "FROM parque_movil WHERE tipo_vehiculo='SEMIRREMOLQUE' AND pais IS NOT NULL "
               "GROUP BY pais ORDER BY value DESC")

    dnrpa = []
    try:
        dnrpa = q("SELECT anio AS label, operacion, SUM(cantidad) AS value "
                  "FROM dnrpa_tramites WHERE tipo_vehiculo LIKE 'SEMIRREMOLQUE%' "
                  "GROUP BY anio, operacion ORDER BY anio")
    except sqlite3.Error:
        pass

    provincias = []
    try:
        provincias = q("SELECT provincia_registro AS label, SUM(cantidad) AS value "
                       "FROM dnrpa_tramites WHERE tipo_vehiculo LIKE 'SEMIRREMOLQUE%' "
                       "AND operacion='inscripcion' AND provincia_registro<>'' "
                       "GROUP BY 1 ORDER BY value DESC LIMIT 12")
    except sqlite3.Error:
        pass

    top = q("SELECT razon_social AS label, cuit, COUNT(*) AS value "
            "FROM v_vehiculos_carga WHERE tipo_vehiculo='SEMIRREMOLQUE' "
            "AND pais='AR' AND dominio_valido=1 AND cuit IS NOT NULL AND cuit<>'' "
            "GROUP BY cuit ORDER BY value DESC LIMIT 15")

    return {"tipos": tipos, "carroceria": carroceria, "anios": anios,
            "paises": paises, "dnrpa": dnrpa, "provincias": provincias, "top_carriers": top}


@app.get("/api/carriers")
def carriers(search: str = "", page: int = 1, size: int = 50,
             solo_activos: bool = False, solo_con_semi: bool = False):
    size = max(1, min(size, 200))
    where, params = ["o.cuit IS NOT NULL", "o.cuit<>''"], []
    if search:
        where.append("(o.razon_social LIKE ? OR o.cuit LIKE ? OR o.email LIKE ? OR e.email LIKE ?)")
        params += [f"%{search}%"] * 4
    if solo_activos:
        where.append("a.cuit IS NOT NULL")
    having = "HAVING semirremolques > 0" if solo_con_semi else ""

    base = f"""
        FROM operadores_cargas o
        LEFT JOIN arca_padron a ON a.cuit = o.cuit
        LEFT JOIN links l ON l.cuit = o.cuit AND l.activo = 1
        LEFT JOIN empresas e ON e.cuit = o.cuit AND e.email IS NOT NULL AND e.email <> ''
        WHERE {' AND '.join(where)}
        GROUP BY o.cuit
        {having}
    """
    rows = q(f"""
        SELECT o.cuit,
               MAX(o.razon_social) AS razon_social,
               COALESCE(MAX(NULLIF(o.email,'')), MAX(NULLIF(e.email,''))) AS email,
               MAX(o.paut)         AS paut,
               MAX(a.denominacion) AS denominacion_arca,
               CASE WHEN MAX(a.cuit) IS NOT NULL THEN 1 ELSE 0 END AS activo_arca,
               MAX(a.imp_iva)      AS iva,
               MAX(o.fecha_inscripcion_cnrt) AS alta_cnrt,
               COUNT(DISTINCT CASE WHEN l.tipo_vehiculo='SEMIRREMOLQUE' THEN l.dominio END) AS semirremolques,
               COUNT(DISTINCT CASE WHEN l.tipo_vehiculo='TRACTOR' THEN l.dominio END)       AS tractores,
               COUNT(DISTINCT l.dominio) AS vehiculos
        {base}
        ORDER BY semirremolques DESC, razon_social
        LIMIT ? OFFSET ?
    """, tuple(params) + (size, (page - 1) * size))

    total = one(f"SELECT COUNT(*) FROM (SELECT o.cuit, "
                f"COUNT(DISTINCT CASE WHEN l.tipo_vehiculo='SEMIRREMOLQUE' THEN l.dominio END) AS semirremolques "
                f"{base})", tuple(params))
    return {"rows": rows, "total": total, "page": page, "size": size}


@app.get("/api/vehicles")
def vehicles(search: str = "", tipo: str = "", page: int = 1, size: int = 50,
             solo_ruta: bool = False):
    size = max(1, min(size, 200))
    where, params = ["pm.pais='AR'"], []
    if tipo:
        where.append("pm.tipo_vehiculo = ?")
        params.append(tipo)
    else:
        where.append("pm.tipo_vehiculo IN ('SEMIRREMOLQUE','TRACTOR','CAMION',"
                     "'CAMIÓN','ACOPLADO','BATEA','CARRETON','CARRETÓN')")
    if search:
        where.append("(pm.dominio LIKE ? OR l.cuit LIKE ? OR l.razon_social LIKE ?)")
        params += [f"%{search}%"] * 3
    if solo_ruta:
        where.append("r.ruta_vigente IN (1,'1','True')")

    base = f"""
        FROM parque_movil pm
        LEFT JOIN links l ON l.dominio = pm.dominio AND l.activo = 1
        LEFT JOIN ruta  r ON r.dominio = pm.dominio
        LEFT JOIN arca_padron a ON a.cuit = l.cuit
        LEFT JOIN empresas e ON e.cuit = l.cuit
        WHERE {' AND '.join(where)}
    """
    rows = q(f"""
        SELECT pm.dominio, pm.tipo_vehiculo, pm.anio_modelo, pm.marca,
               pm.tipo_carroceria, pm.cantidad_ejes,
               l.cuit, l.razon_social,
               COALESCE(NULLIF(l.email,''), NULLIF(e.email,'')) AS email,
               CASE WHEN r.ruta_vigente IN (1,'1','True') THEN 1
                    WHEN r.dominio IS NULL THEN NULL ELSE 0 END AS ruta,
               r.nro_constancia,
               CASE WHEN a.cuit IS NOT NULL THEN 1 ELSE 0 END AS activo_arca
        {base}
        GROUP BY pm.dominio
        ORDER BY pm.dominio LIMIT ? OFFSET ?
    """, tuple(params) + (size, (page - 1) * size))
    total = one(f"SELECT COUNT(DISTINCT pm.dominio) {base}", tuple(params))
    return {"rows": rows, "total": total, "page": page, "size": size}


@app.get("/api/permisos")
def permisos(dominio: str = Query(..., min_length=3)):
    return q("SELECT origen, transito, destino, vigencia_hasta "
             "FROM permisos_internacionales WHERE dominio = ? ORDER BY destino",
             (dominio.upper(),))


def _provenance():
    def n(tbl):
        try:
            return one(f"SELECT COUNT(*) FROM {tbl}")
        except sqlite3.Error:
            return 0
    return [
        {"fuente": "CNRT SEOP", "recurso": "api.cnrt.gob.ar/seop/public/v1/empresas",
         "tabla": "empresas", "filas": n("empresas"),
         "aporta": "Registro de empresas CNRT: CUIT, razon social, email, PAUT"},
        {"fuente": "CNRT SEOP", "recurso": "/v1/operadores?tipoTransporte=1",
         "tabla": "operadores_cargas", "filas": n("operadores_cargas"),
         "aporta": "Habilitaciones de transporte de CARGAS (jurisdiccion internacional)"},
        {"fuente": "CNRT SEOP", "recurso": "/v1/parquesMoviles",
         "tabla": "parque_movil", "filas": n("parque_movil"),
         "aporta": "Parque movil completo: dominio, tipo, anio, marca, carroceria, ejes"},
        {"fuente": "CNRT SEOP", "recurso": "/v1/parquesMovilesOperadores",
         "tabla": "links", "filas": n("links"),
         "aporta": "Vinculo dominio <-> CUIT titular, con fecha de alta y baja"},
        {"fuente": "CNRT consultapme", "recurso": "/api/vehiculo_cargas_habilitadospordocumento",
         "tabla": "flota_internacional", "filas": n("flota_internacional"),
         "aporta": "Flota habilitada por CUIT + permisos MERCOSUR"},
        {"fuente": "CNRT consultapme", "recurso": "/api/ruta_vigente_por_dominio",
         "tabla": "ruta", "filas": n("ruta"),
         "aporta": "RUTA vigente por dominio: constancia y certificado"},
        {"fuente": "ARCA (ex AFIP)", "recurso": "archivoCompleto.asp (padron masivo)",
         "tabla": "arca_padron", "filas": n("arca_padron"),
         "aporta": "Padron de contribuyentes: define CUIT activo"},
        {"fuente": "DNRPA", "recurso": "datos.gob.ar inscripciones / bajas",
         "tabla": "dnrpa_tramites", "filas": n("dnrpa_tramites"),
         "aporta": "Altas y bajas nacionales por tipo, provincia y registro seccional"},
    ]


@app.get("/api/export/{name}")
def export(name: str):
    allowed = {"carriers.csv", "fleet.csv", "semirremolques_activos.csv"}
    if name not in allowed:
        return JSONResponse({"error": "not found"}, status_code=404)
    p = ROOT / "data" / "out" / name
    if not p.exists():
        return JSONResponse({"error": "export not generated yet"}, status_code=404)
    return FileResponse(p, filename=name, media_type="text/csv")
