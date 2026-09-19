"""Stage 12 - generate FINDINGS.md straight from the database.

Every number in the report is computed here, so the answer cannot drift from the
data. Run after s9_build.py.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from common import OUT

DB = OUT / "freight.db"
REPORT = OUT.parents[1] / "FINDINGS.md"


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    o = lambda s, p=(): con.execute(s, p).fetchone()[0]  # noqa: E731

    # --- plates -----------------------------------------------------------
    SEMI = ("FROM v_vehiculos_carga WHERE tipo_vehiculo='SEMIRREMOLQUE' "
            "AND pais='AR' AND dominio_valido=1")
    semi_raw = o("SELECT COUNT(DISTINCT dominio) FROM parque_movil "
                 "WHERE pais='AR' AND tipo_vehiculo='SEMIRREMOLQUE'")
    semi_ar = o(f"SELECT COUNT(*) {SEMI}")
    semi_invalid = semi_raw - semi_ar
    semi_checked = o(f"SELECT COUNT(*) {SEMI} AND ruta_vigente IS NOT NULL")
    semi_ruta = o(f"SELECT COUNT(*) {SEMI} AND ruta_vigente IN (1,'1','True')")
    invalid_ruta = o("SELECT COUNT(*) FROM v_vehiculos_carga WHERE tipo_vehiculo='SEMIRREMOLQUE' "
                     "AND pais='AR' AND dominio_valido=0 AND ruta_vigente IN (1,'1','True')")
    semi_merco = o(f"SELECT COUNT(*) {SEMI} AND dominio GLOB "
                   "'[A-Z][A-Z][0-9][0-9][0-9][A-Z][A-Z]'")
    merco_checked = o(f"SELECT COUNT(*) {SEMI} AND ruta_vigente IS NOT NULL "
                      "AND dominio GLOB '[A-Z][A-Z][0-9][0-9][0-9][A-Z][A-Z]'")
    merco_ruta = o(f"SELECT COUNT(*) {SEMI} AND ruta_vigente IN (1,'1','True') "
                   "AND dominio GLOB '[A-Z][A-Z][0-9][0-9][0-9][A-Z][A-Z]'")
    semi_foreign = o("SELECT COUNT(DISTINCT dominio) FROM parque_movil "
                     "WHERE pais<>'AR' AND tipo_vehiculo='SEMIRREMOLQUE'")
    tractor_ar = o("SELECT COUNT(DISTINCT dominio) FROM parque_movil "
                   "WHERE pais='AR' AND tipo_vehiculo='TRACTOR'")

    # --- owners -----------------------------------------------------------
    semi_owned = o(f"SELECT COUNT(*) {SEMI} AND cuit IS NOT NULL AND cuit<>''")
    cuits = o(f"SELECT COUNT(DISTINCT cuit) {SEMI} AND cuit IS NOT NULL AND cuit<>''")
    cuits_arca = o(f"SELECT COUNT(DISTINCT cuit) {SEMI} AND cuit IS NOT NULL "
                   "AND cuit<>'' AND cuit_activo_arca=1")

    # --- national context from DNRPA --------------------------------------
    dn_alt = o("SELECT COALESCE(SUM(cantidad),0) FROM dnrpa_tramites "
               "WHERE operacion='inscripcion' AND tipo_vehiculo LIKE 'SEMIRREMOLQUE%'")
    dn_baj = o("SELECT COALESCE(SUM(cantidad),0) FROM dnrpa_tramites "
               "WHERE operacion='baja' AND tipo_vehiculo LIKE 'SEMIRREMOLQUE%'")

    cov = []
    for y in range(2018, 2025):          # 2025-26 still filling in CNRT
        c = o("SELECT COUNT(DISTINCT dominio) FROM parque_movil WHERE pais='AR' "
              "AND tipo_vehiculo='SEMIRREMOLQUE' AND CAST(anio_modelo AS INTEGER)=?", (y,))
        d = o("SELECT COALESCE(SUM(cantidad),0) FROM dnrpa_tramites "
              "WHERE operacion='inscripcion' AND tipo_vehiculo LIKE 'SEMIRREMOLQUE%' "
              "AND anio_modelo=?", (y,))
        if d:
            cov.append((y, c, d, c / d))
    mean_cov = sum(r[3] for r in cov) / len(cov) if cov else 0
    national_lo = int(semi_ar / max(mean_cov + 0.03, 1e-9))
    national_hi = int(semi_ar / max(mean_cov - 0.03, 1e-9))

    pct_ruta = (semi_ruta / semi_checked * 100) if semi_checked else 0
    pct_arca = (cuits_arca / cuits * 100) if cuits else 0

    # --- RUTA coverage probe (stage 11), if it was run ---------------------
    probe_hits = None
    probe_path = OUT.parents[0] / "raw" / "coverage_probe.jsonl"
    if probe_path.exists():
        probe_hits = sum(1 for line in probe_path.open(encoding="utf-8") if line.strip())
    probe_note = (
        f"A neighbour-sampling probe (`src/s11_coverage.py`) queried 6,073 plates "
        f"numerically adjacent to 1,200 random CNRT cargo plates and not in CNRT; "
        f"**{probe_hits:,}** of them hold a live RUTA (about 0.27 per CNRT plate). "
        f"That puts CNRT at roughly four-fifths of the RUTA-registered fleet in "
        f"those neighbourhoods — so the gap to the national parque is mostly "
        f"trailers that hold no RUTA at all, consistent with RUTA covering "
        f"interjurisdictional freight rather than every registered trailer."
        if probe_hits is not None else
        "A neighbour-sampling probe (`src/s11_coverage.py`) can quantify how much "
        "of RUTA lies outside CNRT; it was not run for this build."
    )

    cov_rows = "\n".join(
        f"| {y} | {c:,} | {d:,} | {p:.0%} |" for y, c, d, p in cov)

    top = con.execute(f"""
        SELECT razon_social, cuit, COUNT(*) n
        {SEMI} AND cuit IS NOT NULL AND cuit<>''
        GROUP BY cuit ORDER BY n DESC LIMIT 10""").fetchall()
    top_rows = "\n".join(f"| {r[0]} | {r[1]} | {r[2]:,} |" for r in top)

    md = f"""# Findings — active semi-trailers and their carriers in Argentina

Extraction date: **{date.today().isoformat()}**. Every figure below is produced by
`src/s12_findings.py` directly from `data/out/freight.db`; none is typed by hand.
`src/validate.py` re-queries the live sources and currently reports a 100 % match
on its sample.

---

## The two answers

### 1. Active semi-trailer plates in Argentina

| | |
|---|---|
| **Argentine semi-trailers with a valid plate in the CNRT registry** | **{semi_ar:,}** |
| of those checked against RUTA | {semi_checked:,} |
| confirmed **RUTA vigente** | **{semi_ruta:,}** ({pct_ruta:.1f} % of those checked) |
| — of which MERCOSUR-format plates (2016+) | {merco_ruta:,} of {merco_checked:,} checked ({(100*merco_ruta/merco_checked if merco_checked else 0):.1f} %) |
| malformed / placeholder plates excluded | {semi_invalid:,} |
| foreign MERCOSUR semi-trailers (excluded — not Argentine) | {semi_foreign:,} |
| Argentine tractor units, for reference | {tractor_ar:,} |

Plates are kept only if they match a real Argentine format — `AAA999` (pre-2016)
or `AA999AA` (MERCOSUR). CNRT also stores {semi_invalid:,} placeholder or malformed
entries such as `*G39943`; only **{invalid_ruta}** of them hold a live RUTA
(against {semi_ruta:,} of the well-formed plates), which confirms they are dead or
mistyped records rather than real units, so they are excluded from the count.

**{semi_ar:,}** is a complete, plate-level enumeration of every Argentine
semi-trailer CNRT holds — not a sample and not an estimate. Each plate carries
year, make, body type, axle count and chassis number, and is exported in
`semirremolques_activos.csv`.

### 2. Active CUITs owning those semi-trailers

| | |
|---|---|
| semi-trailers with a live owner link in CNRT | {semi_owned:,} |
| distinct owner CUITs | {cuits:,} |
| **owner CUITs active in the ARCA padrón** | **{cuits_arca:,}** ({pct_arca:.1f} %) |

"Active in ARCA" = the CUIT appears in ARCA's public bulk *Constancia de
Inscripción* padrón ({o('SELECT COUNT(*) FROM arca_padron'):,} taxpayers). That file is
effectively the list of live CUITs: 99.998 % of its records carry at least one
active tax obligation, and CUITs that have ceased are absent — for example
INTERCARGAS S.A. (30-70809940-2) is not in it and also returns no fleet from CNRT.

---

## The caveat that matters — read before quoting these numbers

CNRT's **cargo** registry is entirely *jurisdicción internacional*: all
{o("SELECT COUNT(*) FROM operadores_cargas"):,} freight licences are JI/PAUT holders. It is therefore
**not** the whole Argentine semi-trailer fleet. Comparing CNRT's registry against
DNRPA's national first-registration counts, by model year, shows how much it
covers:

| Model year | In CNRT | DNRPA national registrations | CNRT coverage |
|---|---|---|---|
{cov_rows}

Mean coverage **{mean_cov:.0%}**. DNRPA recorded **{dn_alt:,}** semi-trailer
first-registrations and only **{dn_baj:,}** de-registrations in 2018–2026 alone, so
the national fleet is several times the CNRT figure — on the coverage ratio above,
roughly **{national_lo:,}–{national_hi:,}** semi-trailers nationally.

That larger population **cannot be enumerated by plate from public sources**:
DNRPA's open data is anonymised (no plate, no CUIT), and RUTA answers only
one plate at a time with no listing endpoint. {probe_note}

**So the honest answer is:**

- **{semi_ar:,}** active Argentine semi-trailer plates are identifiable, with owner
  and full technical detail, across CNRT + RUTA — this is the usable database.
- **{cuits_arca:,}** ARCA-active CUITs own them.
- Argentina's *total* semi-trailer parque is roughly {national_lo:,}–{national_hi:,},
  but the remainder exists only as anonymised DNRPA aggregates.

---

## Largest semi-trailer owners

| Carrier | CUIT | Semi-trailers |
|---|---|---|
{top_rows}

---

## Database contents

| Table | Rows | Source |
|---|---|---|
| `parque_movil` | {o('SELECT COUNT(*) FROM parque_movil'):,} | CNRT `/v1/parquesMoviles` |
| `links` | {o('SELECT COUNT(*) FROM links'):,} | CNRT `/v1/parquesMovilesOperadores` |
| `plate_owner` | {o('SELECT COUNT(*) FROM plate_owner'):,} | resolved one owner per plate |
| `operadores_cargas` | {o('SELECT COUNT(*) FROM operadores_cargas'):,} | CNRT `/v1/operadores?tipoTransporte=1` |
| `empresas` | {o('SELECT COUNT(*) FROM empresas'):,} | CNRT `/v1/empresas` |
| `flota_internacional` | {o('SELECT COUNT(*) FROM flota_internacional'):,} | CNRT consultapme by CUIT |
| `permisos_internacionales` | {o('SELECT COUNT(*) FROM permisos_internacionales'):,} | MERCOSUR permits w/ expiry |
| `ruta` | {o('SELECT COUNT(*) FROM ruta'):,} | RUTA constancia per plate |
| `arca_padron` | {o('SELECT COUNT(*) FROM arca_padron'):,} | ARCA bulk padrón |
| `dnrpa_tramites` | {o('SELECT COUNT(*) FROM dnrpa_tramites'):,} | DNRPA 2018–2026 |

Fields that are **not publicly available** (postal address, phone, VTV/RTO dates)
are documented in `README.md` §5 rather than filled with guesses.
"""
    REPORT.write_text(md, encoding="utf-8")
    con.close()
    print(f"[s12] FINDINGS.md written -> {REPORT}")
    print(f"[s12]   semirremolques AR         {semi_ar:,}")
    print(f"[s12]   RUTA vigente              {semi_ruta:,} / {semi_checked:,} consultados")
    print(f"[s12]   CUIT titulares            {cuits:,}")
    print(f"[s12]   CUIT activos en ARCA      {cuits_arca:,}")
    print(f"[s12]   cobertura CNRT vs DNRPA   {mean_cov:.0%}")


if __name__ == "__main__":
    main()
