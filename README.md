# Base de Datos de Transporte de Cargas — Argentina

Web-scraping pipeline and dashboard that build a freight-transport database for
Argentina from the official registries: **CNRT**, **RUTA**, **DNRPA** and **ARCA**.

---

## 1. What this answers

The selection question was:

> How many **active semi-trailer license plates** are there in Argentina in these
> databases, and how many **active CUITs** of carriers own those semi-trailers?
> ("Active" means an active CUIT in ARCA.)

The numbers, their exact definitions and their provenance are in
[`FINDINGS.md`](FINDINGS.md). Every figure there is reproducible by re-running the
pipeline; nothing is estimated or interpolated.

---

## 2. Data sources actually used

All four are public and were reached without credentials. No source was scraped
through a login, and no CAPTCHA was circumvented.

| Source | Endpoint / file | What it contributes |
|---|---|---|
| **CNRT SEOP** | `api.cnrt.gob.ar/seop/public/v1/empresas` | Company registry: CUIT, razón social, e-mail, PAUT |
| **CNRT SEOP** | `/v1/operadores?tipoTransporte=1` | Freight (CARGAS AUTOMOTOR) operating licences |
| **CNRT SEOP** | `/v1/parquesMoviles` | Complete vehicle registry: plate, type, year, make, body, axles |
| **CNRT SEOP** | `/v1/parquesMovilesOperadores` | **Plate ↔ CUIT link**, with `fechaAlta` / `fechaBaja` |
| **CNRT consultapme** | `/api/vehiculo_cargas_habilitadospordocumento` | Fleet by CUIT + MERCOSUR permits (origin/transit/destination/expiry) |
| **RUTA** (via CNRT) | `/api/ruta_vigente_por_dominio/{dominio}` | RUTA constancia per plate — the national freight registry test |
| **ARCA** (ex-AFIP) | `afip.gob.ar/genericos/cInscripcion/archivoCompleto.asp` | Full taxpayer padrón (6.17M CUITs) — defines "active CUIT" |
| **DNRPA** | `datos.gob.ar` inscripciones / bajas 2018–2026 | National registrations & de-registrations by type, province, registro seccional |

The CNRT SEOP API was discovered from the JavaScript bundle of
`servicios.cnrt.gob.ar`; it is an unauthenticated, paginated, documented-by-error
REST API (invalid filters return the list of permitted ones). `consultapme.cnrt.gob.ar`
additionally publishes a Swagger-style page at `/api/doc`.

---

## 3. Pipeline

```
src/common.py          shared async HTTP client, retry, resumable JSONL sink
src/s1_empresas.py     CNRT company registry            -> data/raw/empresas.jsonl
src/s2_flota.py        fleet + MERCOSUR permits by CUIT -> data/raw/flota.jsonl
src/s3_parque.py       full CNRT vehicle registry       -> data/raw/parque_movil.jsonl
src/s4_arca.py         ARCA padrón (fixed-width, 6.17M) -> SQLite arca_padron
src/s5_operadores.py   freight operating licences       -> data/raw/operadores_cargas.jsonl
src/s6_links.py        plate <-> CUIT links             -> data/raw/links.jsonl
src/s6b_verify.py      re-count every operator's fleet against the API; repairs short reads
src/s7_ruta.py         RUTA constancia per plate        -> data/raw/ruta.jsonl
src/s8_dnrpa.py        DNRPA national flows             -> SQLite dnrpa_tramites
src/s9_build.py        load + dedupe + join everything  -> data/out/freight.db
src/s10_export.py      delivery CSVs                    -> data/out/*.csv
src/s11_coverage.py    neighbour-sampling probe: how much of RUTA does CNRT hold?
src/s12_findings.py    writes FINDINGS.md from the database (no hand-typed numbers)
src/validate.py        re-queries live sources for a random sample, field by field
ui/app.py              FastAPI read-only API
ui/index.html          dashboard
```

Every network stage is **resumable** — progress is recorded per key (`*.done`,
`*.offsets`, or the JSONL key itself), so an interrupted run continues where it
stopped instead of refetching. A request that never settles (timeout, 5xx after
retries) is left **unrecorded** rather than stored as a negative result, so a
network blip can never masquerade as "this plate has no RUTA" or "this carrier
has no fleet".

### Proving the data

Two independent checks ship with the pipeline:

- `validate.py` draws a random sample from **the database the CSVs are built
  from**, re-queries each originating endpoint live, and compares field by field.
- `s6b_verify.py` asks the API for every cargo operator's authoritative vehicle
  count and compares it with what was stored; any operator that disagrees is
  dropped and refetched.

Both are run before the numbers in `FINDINGS.md` are generated.

### Run it

Three commands from a clean machine (Python 3.12):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run_pipeline.py
```

`run_pipeline.py` sequences the stages, stops at the first failure, and every
stage resumes from where it left off — so if the network drops halfway through
you re-run the same command and it continues. `--list`, `--from s7`,
`--only s9 s10 s12` and `--with-probe` are available. A full first run takes
roughly 3–4 hours, almost all of it the two per-plate/per-operator sweeps
against CNRT; every later run only fetches what changed.

The individual stages are plain scripts in `src/` and can be run on their own.

### Dashboard

```powershell
.venv\Scripts\python.exe -m uvicorn app:app --app-dir ui --port 8000
# http://127.0.0.1:8000
```

### Deployment (GitHub Actions → Netlify)

`.github/workflows/scraper.yml` re-scrapes weekly, then `src/s13_site.py` renders
the same dashboard as a static site (`site/`) which is force-pushed to the
**`site`** branch; Netlify deploys that branch. Step-by-step setup, the smoke
test to run first, and troubleshooting are in **[`DEPLOY.md`](DEPLOY.md)**.

Shows the two headline figures, fleet composition, semi-trailer body types and
model years, DNRPA national flows, the largest fleet owners, and searchable
carrier / vehicle tables with CSV download. Sources tab lists every table with
its row count and the endpoint it came from.

---

## 4. Output

`data/out/freight.db` (SQLite) and three CSVs (`;`-separated, UTF-8 BOM, Excel-ready):

| File | Grain | Key columns |
|---|---|---|
| `carriers.csv` | one row per CUIT | CUIT, razón social, licences, PAUT, international permits, destination countries, e-mail, ARCA status, tractor/semi-trailer counts |
| `fleet.csv` | one row per plate | plate, type, year, make, body type, axles, owner CUIT, RUTA constancia, ARCA status |
| `semirremolques_activos.csv` | one row per semi-trailer | the answer set for the selection question |

### Mapping to the requested structure

| Requested field | Status | Source |
|---|---|---|
| CUIT | ✅ | CNRT SEOP |
| Transport company name | ✅ | CNRT + ARCA denominación |
| Address | ❌ **not public** | see §5 |
| Province | ⚠️ aggregate only | DNRPA registro seccional |
| Owner (titular) | ✅ | CNRT plate↔CUIT link |
| Licences | ✅ | CNRT operating licences (jurisdiction, validity) |
| International permits | ✅ | PAUT + MERCOSUR permits w/ expiry |
| E-mail | ⚠️ partial | CNRT (~10% of freight CUITs) |
| Phone | ❌ **not public** | see §5 |
| Tractor plates (plate/year/model) | ✅ | CNRT parque móvil |
| Tractor VTV/RTO | ❌ **not public** | see §5 |
| Tractor owner registration | ✅ | RUTA constancia + certificate |
| Semi-trailer plates (plate/year/model) | ✅ | CNRT parque móvil |
| Semi-trailer type | ✅ | `tipo_carroceria` |
| Semi-trailer VTV/RTO | ❌ **not public** | see §5 |
| Semi-trailer owner registration | ✅ | RUTA constancia + certificate |

---

## 5. Honest gaps

These fields were requested but **cannot** be obtained from the public sources.
They are reported rather than filled with guesses:

- **VTV / RTO inspection data.** The `consultapme` schema documents
  `vigencia_hasta_inspeccion_tecnica`, `tipo_tecnica` and `tecnica_nro`, but the
  endpoint never populates them, and the HTML results table has no inspection
  column for cargo. The authoritative source is CENT, whose API
  (`api.cent.gov.ar`) does not resolve publicly — so RTO dates would need a CENT
  agreement or a per-plate provincial VTV lookup.
- **Postal address and phone numbers.** No CNRT endpoint exposes them; the ARCA
  bulk padrón carries only CUIT, denomination and tax condition. ARCA's *domicilio
  fiscal* is behind the CAPTCHA-protected constancia form, and its web service
  (`ws_sr_constancia_inscripcion`) requires the client's own X.509 certificate.
  With that certificate this pipeline can add address in one extra stage.
- **E-mail coverage** is ~10% of freight CUITs — that is what CNRT holds, not a
  scraping limitation.

## 6. Coverage caveat that matters

CNRT's **cargo** operator data is entirely **jurisdicción internacional (JI)** —
24,021 licences, all PAUT holders. Argentina's purely *domestic* freight carriers
are registered in **RUTA**, which CNRT exposes only per-plate (no listing
endpoint), so RUTA cannot be enumerated — it can only confirm plates already
known. Consequently the plate universe here is the CNRT vehicle registry, and
RUTA is used as the activity test on top of it. `FINDINGS.md` states which figure
is a full count and which is a lower bound.
