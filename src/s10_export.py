"""Stage 10 - export the delivery CSVs in the structure the brief asks for.

Three files, all UTF-8 with BOM so they open cleanly in Excel in Argentina:

  carriers.csv              one row per carrier CUIT - identity, licences,
                            international permits, contact, fleet counts
  fleet.csv                 one row per vehicle plate - tractors and
                            semi-trailers with their owner, RUTA and ARCA status
  semirremolques_activos.csv  the answer set for the selection question:
                            active Argentine semi-trailer plates and their
                            ARCA-active owner CUITs
"""
from __future__ import annotations

import csv
import sqlite3

from common import OUT

DB = OUT / "freight.db"
ENC = "utf-8-sig"


def dump(con, path, sql, header):
    cur = con.execute(sql)
    n = 0
    with open(path, "w", newline="", encoding=ENC) as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        for row in cur:
            w.writerow(["" if v is None else v for v in row])
            n += 1
    print(f"[s10] {path.name:<30} {n:>9,} rows")
    return n


def main() -> None:
    con = sqlite3.connect(DB)

    # ---------------- carriers -------------------------------------------
    dump(con, OUT / "carriers.csv", """
        WITH flota AS (
            SELECT cuit,
                   COUNT(DISTINCT CASE WHEN tipo_vehiculo='SEMIRREMOLQUE' THEN dominio END) AS semirremolques,
                   COUNT(DISTINCT CASE WHEN tipo_vehiculo='TRACTOR'       THEN dominio END) AS tractores,
                   COUNT(DISTINCT dominio)                                                  AS vehiculos_total
            FROM links WHERE activo=1 AND cuit IS NOT NULL AND cuit<>''
            GROUP BY cuit
        ),
        permisos AS (
            SELECT cuit,
                   GROUP_CONCAT(DISTINCT destino) AS paises_destino,
                   COUNT(*)                       AS permisos_internacionales
            FROM permisos_internacionales WHERE cuit IS NOT NULL AND cuit<>''
            GROUP BY cuit
        ),
        op AS (
            SELECT cuit,
                   MAX(razon_social) AS razon_social,
                   MAX(email)        AS email,
                   MAX(paut)         AS paut,
                   GROUP_CONCAT(DISTINCT jurisdiccion) AS jurisdicciones,
                   MAX(fecha_inscripcion_cnrt) AS fecha_inscripcion_cnrt,
                   MAX(vigencia_hasta) AS vigencia_hasta,
                   MAX(vigente)        AS vigente,
                   COUNT(*)            AS habilitaciones
            FROM operadores_cargas WHERE cuit IS NOT NULL AND cuit<>''
            GROUP BY cuit
        )
        SELECT
            op.cuit,
            op.razon_social,
            a.denominacion,
            ''                                   AS domicilio,
            ''                                   AS provincia,
            op.razon_social                      AS titular,
            op.habilitaciones,
            op.jurisdicciones,
            op.paut,
            COALESCE(p.permisos_internacionales,0),
            p.paises_destino,
            op.email,
            ''                                   AS telefono,
            op.fecha_inscripcion_cnrt,
            op.vigencia_hasta,
            op.vigente,
            CASE WHEN a.cuit IS NOT NULL THEN 'SI' ELSE 'NO' END AS cuit_activo_arca,
            a.imp_iva, a.imp_ganancias, a.empleador,
            COALESCE(f.tractores,0),
            COALESCE(f.semirremolques,0),
            COALESCE(f.vehiculos_total,0)
        FROM op
        LEFT JOIN flota    f ON f.cuit = op.cuit
        LEFT JOIN permisos p ON p.cuit = op.cuit
        LEFT JOIN arca_padron a ON a.cuit = op.cuit
        ORDER BY COALESCE(f.semirremolques,0) DESC, op.razon_social
    """, [
        "cuit", "razon_social_cnrt", "denominacion_arca", "domicilio", "provincia",
        "titular", "habilitaciones_cnrt", "jurisdicciones", "paut",
        "permisos_internacionales", "paises_destino", "email", "telefono",
        "fecha_inscripcion_cnrt", "vigencia_hasta", "vigente", "cuit_activo_arca",
        "arca_iva", "arca_ganancias", "arca_empleador",
        "tractores", "semirremolques", "vehiculos_total",
    ])

    # ---------------- fleet ----------------------------------------------
    dump(con, OUT / "fleet.csv", """
        SELECT dominio, tipo_vehiculo, anio_modelo, marca, modelo,
               tipo_carroceria, cantidad_ejes, nro_chasis, peso_maximo, carga_util,
               cuit, razon_social, email, paut, jurisdiccion,
               link_fecha_alta, link_fecha_baja,
               CASE WHEN ruta_vigente IN (1,'1','True') THEN 'SI'
                    WHEN ruta_vigente IS NULL THEN '' ELSE 'NO' END,
               ruta_constancia, ruta_certificado, ruta_fecha_alta,
               CASE WHEN cuit_activo_arca=1 THEN 'SI' ELSE 'NO' END,
               arca_denominacion
        FROM v_vehiculos_carga
        ORDER BY tipo_vehiculo, dominio
    """, [
        "dominio", "tipo_vehiculo", "anio_modelo", "marca", "modelo",
        "tipo_carroceria", "cantidad_ejes", "nro_chasis", "peso_maximo", "carga_util",
        "cuit_titular", "razon_social_titular", "email", "paut", "jurisdiccion",
        "alta_en_operador", "baja_en_operador",
        "ruta_vigente", "ruta_nro_constancia", "ruta_nro_certificado", "ruta_fecha_alta",
        "cuit_activo_arca", "denominacion_arca",
    ])

    # ---------------- the selection-question answer set -------------------
    dump(con, OUT / "semirremolques_activos.csv", """
        SELECT v.dominio, v.anio_modelo, v.marca, v.tipo_carroceria, v.cantidad_ejes,
               v.cuit, v.razon_social, v.email,
               CASE WHEN v.cuit_activo_arca=1 THEN 'SI' ELSE 'NO' END,
               CASE WHEN v.ruta_vigente IN (1,'1','True') THEN 'SI'
                    WHEN v.ruta_vigente IS NULL THEN 'SIN CONSULTAR' ELSE 'NO' END,
               v.ruta_constancia
        FROM v_vehiculos_carga v
        WHERE v.tipo_vehiculo = 'SEMIRREMOLQUE' AND v.pais = 'AR'
        ORDER BY v.dominio
    """, [
        "dominio", "anio_modelo", "marca", "tipo_semirremolque", "cantidad_ejes",
        "cuit_titular", "razon_social_titular", "email",
        "cuit_activo_arca", "ruta_vigente", "ruta_nro_constancia",
    ])

    con.close()
    print(f"[s10] DONE -> {OUT}")


if __name__ == "__main__":
    main()
