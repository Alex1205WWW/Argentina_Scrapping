# Deployment roadmap — GitHub Actions → `site` branch → Netlify

```
 main (code only)                      site (generated, 1 commit, ~35 MB)
 ────────────────                      ──────────────────────────────────
 src/  ui/  run_pipeline.py            index.html   findings.html   netlify.toml
 .github/workflows/scraper.yml  ──►    data/*.json   downloads/*.csv  FINDINGS.md
          │  weekly, or "Run workflow"            │
          │  ~3.5 h on ubuntu-latest              │  Netlify watches this branch
          ▼                                       ▼
   run_pipeline.py --fresh  ──►  s13_site.py  ──►  https://<your-site>.netlify.app
```

The dashboard is one `index.html` that runs in two modes. Locally it talks to
FastAPI; on Netlify `s13_site.py` injects `<meta name="data-mode" content="static">`
and the page reads pre-rendered `data/*.json` instead, doing search, filters and
pagination in the browser. Same page, same queries, no server.

---

## Step 1 — repo hygiene (once, on your PC)

`main` must hold code only. CI regenerates the CSVs every run and publishes
them on the `site` branch, so the copies tracked on `main` today would only go
stale (and `fleet.csv` is 18 MB per commit).

```powershell
cd D:\Scrapping
git rm --cached data/out/carriers.csv data/out/fleet.csv data/out/semirremolques_activos.csv
git add .gitignore .github/workflows/scraper.yml run_pipeline.py src/s13_site.py ui/app.py ui/index.html DEPLOY.md README.md
git commit -m "ci: scrape weekly, publish static site to the site branch for Netlify"
git push origin main
```

The files stay on your disk; they just stop being tracked.

## Step 2 — smoke test from GitHub (2 minutes)

The one real risk: GitHub's runners are US-based, and Argentine government
hosts may throttle or block them. Test connectivity **before** committing to a
3-hour run.

1. GitHub → your repo → **Actions** → *Scrape & publish* → **Run workflow**
2. In **stages** type: `s1 s5` → **Run workflow**
3. Wait ~2 min. Green = `api.cnrt.gob.ar` answers from GitHub. Done, go to Step 3.

If it fails on connection/timeouts/HTTP 403, the runner is being blocked.
Fallback — a self-hosted runner on your own PC (it has already proven it can
reach every source):

- repo → **Settings → Actions → Runners → New self-hosted runner → Windows**
- run the 4 commands GitHub shows (download, configure, `./run.cmd`)
- in `scraper.yml` change `runs-on: ubuntu-latest` → `runs-on: self-hosted`,
  and the `run:` step's shell to PowerShell (`shell: pwsh`, replace the `if` with
  `if ($env:STAGES) { python -u run_pipeline.py --only $env:STAGES.Split() } else { python -u run_pipeline.py --fresh }`)
- keep the PC on when the schedule fires

## Step 3 — first full run (~3.5 h)

**Actions → Run workflow**, leave *stages* blank → Run.

What happens: `run_pipeline.py --fresh` re-scrapes every registry, verifies,
builds `freight.db`, exports the CSVs, writes `FINDINGS.md`, re-checks a live
sample, then `s13_site.py` builds `site/`. The last step force-pushes `site/` to
a branch called **`site`** (one orphan commit, replaced every run). A `site`
artifact is also attached to the run for 7 days so you can download and inspect
it.

When it's green: repo → branch dropdown → you'll see **`site`** with
`index.html`, `data/`, `downloads/`, `netlify.toml`.

## Step 4 — connect Netlify (once, 3 minutes)

1. app.netlify.com → **Add new site → Import an existing project → GitHub**
2. Authorise, pick **Alex1205WWW/Argentina_Scrapping**
3. Settings:
   - **Branch to deploy:** `site`
   - **Base directory:** *(empty)*
   - **Build command:** *(empty)*
   - **Publish directory:** `.`
   (the branch's `netlify.toml` sets the same, so defaults also work)
4. **Deploy site.** ~30 s later you have `https://<random-name>.netlify.app`.
   Site settings → *Change site name* to pick a readable subdomain, or add a
   custom domain.

From now on every push to `site` — i.e. every scrape run — redeploys
automatically. No Netlify tokens or GitHub secrets are involved.

## Step 5 — schedule

`scraper.yml` runs **Sundays 03:00 UTC** (Saturday midnight in Buenos Aires).
Weekly is deliberate: a run is ~3.5 hours of ~10 req/s against public
government APIs and the registries change slowly. To change it edit the `cron`
line (`"0 3 * * 1,4"` = Mondays and Thursdays). Cron uses UTC.

## Everyday checks

| Want to… | Do |
|---|---|
| see what's live | the Netlify URL; **Informe** button opens the rendered FINDINGS |
| preview the static site locally | `python src/s13_site.py` then `python -m http.server -d site 8080` → http://localhost:8080 |
| inspect a run's output without Netlify | Actions → the run → **Artifacts → site** |
| re-run just the build after a data fix | Run workflow with stages `s9 s10 s12 site` |
| refresh without waiting for Sunday | Run workflow, stages blank |

## Troubleshooting

- **"Branch `site` not found" in Netlify** — no full run has completed yet. Do Step 3 first.
- **Run cancelled at 350 min** — the APIs were unusually slow. Just re-run: every
  stage resumes from its `.done` / `.offsets` file, so the second attempt only
  fetches what's missing. (Only `--fresh` starts over, and only at the *start* of
  a run.)
- **`val` stage reports mismatches** — the sources changed between scrape and
  check (a plate re-registered mid-run). Harmless at the 1–2 row level; re-run
  if it's more.
- **Netlify shows old numbers** — `data/*.json` is cached 1 h (`netlify.toml`);
  hard-refresh, or wait.
- **Repo size** — `site` is a single orphan commit (`force_orphan: true`), so it
  never grows; `main` never receives generated files.

## Alternative: deploy from Actions with the Netlify CLI

If you would rather not have Netlify watch a branch: add repo secrets
`NETLIFY_AUTH_TOKEN` (Netlify → User settings → Applications → Personal access
tokens) and `NETLIFY_SITE_ID` (Site settings → General → Site ID), replace the
last step with

```yaml
      - name: Deploy to Netlify
        if: ${{ inputs.stages == '' }}
        run: npx --yes netlify-cli deploy --prod --dir=site --message "scrape ${{ github.run_id }}"
        env:
          NETLIFY_AUTH_TOKEN: ${{ secrets.NETLIFY_AUTH_TOKEN }}
          NETLIFY_SITE_ID: ${{ secrets.NETLIFY_SITE_ID }}
```

and create the Netlify site as a manual-deploy site (no Git link). Same result;
the branch approach was chosen because it needs no secrets and leaves an
inspectable copy of every publish in the repo.
