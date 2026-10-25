# Findings — active semi-trailers and their carriers in Argentina

Extraction date: **2026-10-25**. Every figure below is produced by
`src/s12_findings.py` directly from `data/out/freight.db`; none is typed by hand.
`src/validate.py` re-queries the live sources and currently reports a 100 % match
on its sample.

---

## The two answers

### 1. Active semi-trailer plates in Argentina

| | |
|---|---|
| **Argentine semi-trailers with a valid plate in the CNRT registry** | **50,309** |
| of those checked against RUTA | 50,309 |
| confirmed **RUTA vigente** | **0** (0.0 % of those checked) |
| — of which MERCOSUR-format plates (2016+) | 0 of 13,519 checked (0.0 %) |
| malformed / placeholder plates excluded | 2,074 |
| foreign MERCOSUR semi-trailers (excluded — not Argentine) | 109,969 |
| Argentine tractor units, for reference | 50,031 |

Plates are kept only if they match a real Argentine format — `AAA999` (pre-2016)
or `AA999AA` (MERCOSUR). CNRT also stores 2,074 placeholder or malformed
entries such as `*G39943`; only **0** of them hold a live RUTA
(against 0 of the well-formed plates), which confirms they are dead or
mistyped records rather than real units, so they are excluded from the count.

**50,309** is a complete, plate-level enumeration of every Argentine
semi-trailer CNRT holds — not a sample and not an estimate. Each plate carries
year, make, body type, axle count and chassis number, and is exported in
`semirremolques_activos.csv`.

### 2. Active CUITs owning those semi-trailers

| | |
|---|---|
| semi-trailers with a live owner link in CNRT | 40,939 |
| distinct owner CUITs | 3,990 |
| **owner CUITs active in the ARCA padrón** | **2,833** (71.0 %) |

"Active in ARCA" = the CUIT appears in ARCA's public bulk *Constancia de
Inscripción* padrón (6,211,641 taxpayers). That file is
effectively the list of live CUITs: 99.998 % of its records carry at least one
active tax obligation, and CUITs that have ceased are absent — for example
INTERCARGAS S.A. (30-70809940-2) is not in it and also returns no fleet from CNRT.

---

## The caveat that matters — read before quoting these numbers

CNRT's **cargo** registry is entirely *jurisdicción internacional*: all
24,143 freight licences are JI/PAUT holders. It is therefore
**not** the whole Argentine semi-trailer fleet. Comparing CNRT's registry against
DNRPA's national first-registration counts, by model year, shows how much it
covers:

| Model year | In CNRT | DNRPA national registrations | CNRT coverage |
|---|---|---|---|
| 2018 | 1,308 | 7,116 | 18% |
| 2019 | 931 | 4,739 | 20% |
| 2020 | 1,120 | 4,654 | 24% |
| 2021 | 1,719 | 6,913 | 25% |
| 2022 | 1,811 | 7,444 | 24% |
| 2023 | 1,571 | 7,030 | 22% |
| 2024 | 1,089 | 5,868 | 19% |

Mean coverage **22%**. DNRPA recorded **59,373** semi-trailer
first-registrations and only **2,747** de-registrations in 2018–2026 alone, so
the national fleet is several times the CNRT figure — on the coverage ratio above,
roughly **203,336–268,433** semi-trailers nationally.

That larger population **cannot be enumerated by plate from public sources**:
DNRPA's open data is anonymised (no plate, no CUIT), and RUTA answers only
one plate at a time with no listing endpoint. A neighbour-sampling probe (`src/s11_coverage.py`) can quantify how much of RUTA lies outside CNRT; it was not run for this build.

**So the honest answer is:**

- **50,309** active Argentine semi-trailer plates are identifiable, with owner
  and full technical detail, across CNRT + RUTA — this is the usable database.
- **2,833** ARCA-active CUITs own them.
- Argentina's *total* semi-trailer parque is roughly 203,336–268,433,
  but the remainder exists only as anonymised DNRPA aggregates.

---

## Largest semi-trailer owners

| Carrier | CUIT | Semi-trailers |
|---|---|---|
| VICTOR MASSON TTES. CRUZ DEL SUR S.A. | 30556565798 | 453 |
| EMPRESA DE TTES. DON PEDRO S.R.L. | 30595793404 | 435 |
| TTES. VESPRINI S.A. | 30693761731 | 429 |
| TTE. C.D.C. S.A. | 30594711722 | 316 |
| TTES. EL CHOLO S.A. | 30658183636 | 302 |
| TTES. FURLONG S.A. | 30519071521 | 293 |
| TTES. MESSINA S.A. | 33683190239 | 284 |
| PETROVALLE S.A.T. | 30612310900 | 259 |
| TRANSCHEMICAL S.A. | 30702978838 | 258 |
| TRANSOL S.R.L. | 30654254288 | 251 |

---

## Database contents

| Table | Rows | Source |
|---|---|---|
| `parque_movil` | 447,102 | CNRT `/v1/parquesMoviles` |
| `links` | 1,113,007 | CNRT `/v1/parquesMovilesOperadores` |
| `plate_owner` | 95,797 | resolved one owner per plate |
| `operadores_cargas` | 24,143 | CNRT `/v1/operadores?tipoTransporte=1` |
| `empresas` | 58,184 | CNRT `/v1/empresas` |
| `flota_internacional` | 61,828 | CNRT consultapme by CUIT |
| `permisos_internacionales` | 140,269 | MERCOSUR permits w/ expiry |
| `ruta` | 52,383 | RUTA constancia per plate |
| `arca_padron` | 6,211,641 | ARCA bulk padrón |
| `dnrpa_tramites` | 334,062 | DNRPA 2018–2026 |

Fields that are **not publicly available** (postal address, phone, VTV/RTO dates)
are documented in `README.md` §5 rather than filled with guesses.
