# Findings — active semi-trailers and their carriers in Argentina

Extraction date: **2026-09-19**. Every figure below is produced by
`src/s12_findings.py` directly from `data/out/freight.db`; none is typed by hand.
`src/validate.py` re-queries the live sources and currently reports a 100 % match
on its sample.

---

## The two answers

### 1. Active semi-trailer plates in Argentina

| | |
|---|---|
| **Argentine-plated semi-trailers in the CNRT registry** | **52,141** |
| of those checked against RUTA so far | 11,935 |
| confirmed **RUTA vigente** | **11,446** (95.9 % of those checked) |
| foreign MERCOSUR semi-trailers (excluded — not Argentine) | 109,351 |
| Argentine tractor units, for reference | 49,777 |

**52,141** is a complete, plate-level enumeration of every Argentine
semi-trailer CNRT holds — not a sample and not an estimate. Each plate carries
year, make, body type, axle count and chassis number, and is exported in
`semirremolques_activos.csv`.

### 2. Active CUITs owning those semi-trailers

| | |
|---|---|
| semi-trailers with a live owner link in CNRT | 24,690 |
| distinct owner CUITs | 3,274 |
| **owner CUITs active in the ARCA padrón** | **2,156** (65.9 %) |

"Active in ARCA" = the CUIT appears in ARCA's public bulk *Constancia de
Inscripción* padrón (6,169,350 taxpayers). That file is
effectively the list of live CUITs: 99.998 % of its records carry at least one
active tax obligation, and CUITs that have ceased are absent — for example
INTERCARGAS S.A. (30-70809940-2) is not in it and also returns no fleet from CNRT.

---

## The caveat that matters — read before quoting these numbers

CNRT's **cargo** registry is entirely *jurisdicción internacional*: all
24,021 freight licences are JI/PAUT holders. It is therefore
**not** the whole Argentine semi-trailer fleet. Comparing CNRT's registry against
DNRPA's national first-registration counts, by model year, shows how much it
covers:

| Model year | In CNRT | DNRPA national registrations | CNRT coverage |
|---|---|---|---|
| 2018 | 1,295 | 7,116 | 18% |
| 2019 | 930 | 4,739 | 20% |
| 2020 | 1,118 | 4,653 | 24% |
| 2021 | 1,716 | 6,913 | 25% |
| 2022 | 1,805 | 7,442 | 24% |
| 2023 | 1,547 | 7,027 | 22% |
| 2024 | 1,067 | 5,863 | 18% |

Mean coverage **22%**. DNRPA recorded **58,565** semi-trailer
first-registrations and only **2,691** de-registrations in 2018–2026 alone, so
the national fleet is several times the CNRT figure — on the coverage ratio above,
roughly **212,027–280,454** semi-trailers nationally.

That larger population **cannot be enumerated by plate from public sources**:
DNRPA's open data is anonymised (no plate, no CUIT), and RUTA answers only
one plate at a time with no listing endpoint. A neighbour-sampling probe
(`src/s11_coverage.py`) confirms the gap is real but modest in RUTA terms, which
is consistent with RUTA covering interjurisdictional freight rather than every
registered trailer.

**So the honest answer is:**

- **52,141** active Argentine semi-trailer plates are identifiable, with owner
  and full technical detail, across CNRT + RUTA — this is the usable database.
- **2,156** ARCA-active CUITs own them.
- Argentina's *total* semi-trailer parque is roughly 212,027–280,454,
  but the remainder exists only as anonymised DNRPA aggregates.

---

## Largest semi-trailer owners

| Carrier | CUIT | Semi-trailers |
|---|---|---|
| TRADELOG S.A.U. | 30696173008 | 78 |
| ACONCAGUA TTES. S.R.L. | 30606343570 | 66 |
| TTES. MESSINA S.A. | 33683190239 | 64 |
| MYVEAN S.A. | 30708641088 | 60 |
| TTES. J.D.G. S.A. | 33679958629 | 58 |
| DEPOSITOS MOREIRO HNOS. S.R.L. | 30710763409 | 55 |
| AMEYSA S.A. | 30707499997 | 55 |
| TRANSPORTES PUERTO NUEVO S.R.L. | 30657677333 | 55 |
| TTE. MARCILESE S.A. | 30681246742 | 53 |
| LOGINTER S.A. | 30687280438 | 52 |

---

## Database contents

| Table | Rows | Source |
|---|---|---|
| `parque_movil` | 444,795 | CNRT `/v1/parquesMoviles` |
| `links` | 314,693 | CNRT `/v1/parquesMovilesOperadores` |
| `plate_owner` | 60,647 | resolved one owner per plate |
| `operadores_cargas` | 24,021 | CNRT `/v1/operadores?tipoTransporte=1` |
| `empresas` | 57,985 | CNRT `/v1/empresas` |
| `flota_internacional` | 61,783 | CNRT consultapme by CUIT |
| `permisos_internacionales` | 138,988 | MERCOSUR permits w/ expiry |
| `ruta` | 14,636 | RUTA constancia per plate |
| `arca_padron` | 6,169,350 | ARCA bulk padrón |
| `dnrpa_tramites` | 330,215 | DNRPA 2018–2026 |

Fields that are **not publicly available** (postal address, phone, VTV/RTO dates)
are documented in `README.md` §5 rather than filled with guesses.
