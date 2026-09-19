"""Stage 4 - load the ARCA (ex-AFIP) taxpayer padron into SQLite.

Source: the public bulk "Constancia de Inscripcion" file published at
www.afip.gob.ar/genericos/cInscripcion/archivoCompleto.asp - 6.1M fixed-width
records, one per registered taxpayer. This is what decides whether a carrier's
CUIT is ACTIVE in ARCA, which is the project's definition of an active carrier.

Layout (51 chars/record, latin-1):
   0-11  CUIT
  11-41  Apellido y Nombre / Denominacion
  41-43  Impuesto a las Ganancias   AC | NI | EX | NC
  43-45  Impuesto al Valor Agregado AC | NI | EX | NA | XN | AN
  45-47  Monotributo                category letter | NI
  47-48  Integrante de sociedad     S | N
  48-49  Empleador                  S | N
  49-51  Actividad monotributo
"""
from __future__ import annotations

import sqlite3
import zipfile

from common import OUT, RAW

ZIP = RAW / "arca_padron.zip"
DB = OUT / "freight.db"

ACTIVE_IVA = {"AC", "EX", "NA", "XN", "AN"}


def is_active(gan: str, iva: str, mono: str, empleador: str) -> bool:
    """Active = registered in ARCA under at least one live tax obligation."""
    if gan == "AC":
        return True
    if iva in ACTIVE_IVA:
        return True
    if mono not in ("NI", "  ", ""):   # a monotributo category letter
        return True
    return empleador == "S"


def main() -> None:
    con = sqlite3.connect(DB)
    con.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        DROP TABLE IF EXISTS arca_padron;
        CREATE TABLE arca_padron (
            cuit            TEXT PRIMARY KEY,
            denominacion    TEXT,
            imp_ganancias   TEXT,
            imp_iva         TEXT,
            monotributo     TEXT,
            integrante_soc  TEXT,
            empleador       TEXT,
            actividad_mono  TEXT,
            activo          INTEGER
        );
    """)

    zf = zipfile.ZipFile(ZIP)
    name = zf.infolist()[0].filename
    total = active = 0
    batch = []

    with zf.open(name) as fh:
        for raw in fh:
            s = raw.decode("latin-1").rstrip("\n")
            if len(s) < 51:
                continue
            cuit = s[0:11]
            gan, iva, mono = s[41:43], s[43:45], s[45:47]
            intsoc, empl, actmono = s[47:48], s[48:49], s[49:51]
            act = is_active(gan, iva, mono, empl)
            active += act
            total += 1
            batch.append((cuit, s[11:41].strip(), gan.strip(), iva.strip(),
                          mono.strip(), intsoc, empl, actmono, int(act)))
            if len(batch) >= 100_000:
                con.executemany("INSERT OR REPLACE INTO arca_padron VALUES (?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
                print(f"[s4] {total:,} loaded", flush=True)

    if batch:
        con.executemany("INSERT OR REPLACE INTO arca_padron VALUES (?,?,?,?,?,?,?,?,?)", batch)
    con.commit()
    con.execute("CREATE INDEX IF NOT EXISTS ix_arca_activo ON arca_padron(activo)")
    con.commit()
    con.close()
    print(f"[s4] DONE records={total:,} active={active:,} -> {DB}", flush=True)


if __name__ == "__main__":
    main()
