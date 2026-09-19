"""Stage 8 - DNRPA national vehicle-registration records.

DNRPA publishes every automotor transaction as open data on datos.gob.ar. The
files are anonymised - no plate, no CUIT - but they do carry the vehicle type
(SEMIRREMOLQUE / TRACTOR / ACOPLADO / CAMION), the registro seccional that holds
the title, the province and whether the title-holder is a natural or legal
person. That is what lets the freight database report national fleet flows and
cross-check the CNRT plate counts.

Downloads the yearly ZIPs for "inscripciones iniciales" (registrations) and
"bajas" (de-registrations) and writes the freight-relevant rows to SQLite.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
import zipfile

import httpx

from common import HEADERS, OUT, RAW

CKAN = "https://datos.gob.ar/api/3/action/package_show?id="
DATASETS = {"inscripcion": "inscripciones-iniciales-de-autos", "baja": "bajas-de-autos"}
DB = OUT / "freight.db"

FREIGHT_KEYWORDS = ("SEMIRREMOLQUE", "ACOPLADO", "TRACTOR", "CAMION", "CAMIÓN",
                    "CHASIS", "BATEA", "CARRETON", "CARRETÓN", "FURGON", "FURGÓN")


def is_freight(tipo: str) -> bool:
    t = (tipo or "").upper()
    return any(k in t for k in FREIGHT_KEYWORDS)


def resources(dataset: str) -> list[tuple[str, str]]:
    with httpx.Client(headers=HEADERS, timeout=120.0, follow_redirects=True) as c:
        d = c.get(CKAN + dataset).json()["result"]
    out = []
    for res in d["resources"]:
        if res.get("format") == "ZIP":
            out.append((res["name"], res["url"]))
    return out


def fetch(url: str, dest) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    print(f"    downloading {dest.name} ...", flush=True)
    with httpx.Client(headers=HEADERS, timeout=600.0, follow_redirects=True) as c:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)


def rows_from_zip(path):
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            with z.open(info) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace")
                for row in csv.DictReader(text):
                    yield row


def main() -> None:
    years = set(sys.argv[1:]) or None
    con = sqlite3.connect(DB)
    con.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        DROP TABLE IF EXISTS dnrpa_tramites;
        CREATE TABLE dnrpa_tramites (
            operacion        TEXT,
            anio             INTEGER,
            tipo_vehiculo    TEXT,
            marca            TEXT,
            modelo           TEXT,
            anio_modelo      INTEGER,
            uso              TEXT,
            registro_seccional TEXT,
            provincia_registro TEXT,
            titular_tipo_persona TEXT,
            titular_provincia  TEXT,
            titular_localidad  TEXT,
            cantidad         INTEGER
        );
    """)

    agg: dict[tuple, int] = {}
    for op, dataset in DATASETS.items():
        print(f"[s8] {op}: {dataset}", flush=True)
        for name, url in resources(dataset):
            year = "".join(c for c in name if c.isdigit())[-4:]
            if years and year not in years:
                continue
            dest = RAW / url.rsplit("/", 1)[-1]
            try:
                fetch(url, dest)
            except Exception as e:                      # noqa: BLE001
                print(f"    SKIP {name}: {e}", flush=True)
                continue
            n = kept = 0
            for row in rows_from_zip(dest):
                n += 1
                tipo = row.get("automotor_tipo_descripcion") or ""
                if not is_freight(tipo):
                    continue
                kept += 1
                key = (
                    op, int(year), tipo.strip(),
                    (row.get("automotor_marca_descripcion") or "").strip(),
                    (row.get("automotor_modelo_descripcion") or "").strip(),
                    int(row["automotor_anio_modelo"]) if (row.get("automotor_anio_modelo") or "").isdigit() else None,
                    (row.get("automotor_uso_descripcion") or "").strip(),
                    (row.get("registro_seccional_descripcion") or "").strip(),
                    (row.get("registro_seccional_provincia") or "").strip(),
                    (row.get("titular_tipo_persona") or "").strip(),
                    (row.get("titular_domicilio_provincia") or "").strip(),
                    (row.get("titular_domicilio_localidad") or "").strip(),
                )
                agg[key] = agg.get(key, 0) + 1
            print(f"    {name}: rows={n:,} freight={kept:,}", flush=True)

    con.executemany(
        "INSERT INTO dnrpa_tramites VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(*k, v) for k, v in agg.items()],
    )
    con.commit()
    tot = con.execute("SELECT COALESCE(SUM(cantidad),0) FROM dnrpa_tramites").fetchone()[0]
    semi = con.execute(
        "SELECT COALESCE(SUM(cantidad),0) FROM dnrpa_tramites WHERE tipo_vehiculo LIKE 'SEMIRREMOLQUE%'"
    ).fetchone()[0]
    con.execute("CREATE INDEX IF NOT EXISTS ix_dnrpa_tipo ON dnrpa_tramites(tipo_vehiculo)")
    con.commit()
    con.close()
    print(f"[s8] DONE groups={len(agg):,} freight_tramites={tot:,} semirremolques={semi:,} -> {DB}", flush=True)


if __name__ == "__main__":
    main()
