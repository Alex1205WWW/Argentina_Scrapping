"""Stage 13 - build the static site that Netlify serves.

The live dashboard is FastAPI + a 900 MB SQLite file, which static hosting cannot
run. This stage pre-renders exactly what the API would answer into site/data/*.json
and copies the dashboard page with a <meta name="data-mode" content="static">
switch, so the same index.html filters, searches and paginates in the browser.

It reuses ui/app.py's own query functions - no second copy of any SQL - so the
static site can never disagree with the live one.

Output (site/, committed to the `site` branch by GitHub Actions):
  index.html            the dashboard, static mode
  findings.html         FINDINGS.md rendered in the browser
  data/stats.json       headline numbers (+ generated_at)
  data/charts.json      every chart's series
  data/provenance.json  sources table
  data/carriers.json    all carriers   {columns, rows}   ~0.7 MB
  data/vehicles.json    all AR cargo plates {columns, rows} ~11 MB (2 MB compressed)
  downloads/            the three CSVs + FINDINGS.md
  netlify.toml          publish dir + cache headers
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys

from common import OUT, ROOT

sys.path.insert(0, str(ROOT / "ui"))
import app as dashboard  # noqa: E402  - the live dashboard's query layer

SITE = ROOT / "site"
CSVS = ("carriers.csv", "fleet.csv", "semirremolques_activos.csv")

FINDINGS_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Findings - Transporte de Cargas Argentina</title>
<style>
 body{max-width:880px;margin:40px auto;padding:0 20px;background:#f9f9f7;color:#0b0b0b;
      font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
 a{color:#2a78d6} table{border-collapse:collapse;margin:12px 0;font-size:14px}
 td,th{border:1px solid #e1e0d9;padding:6px 10px;text-align:left} code{font-size:13px}
 @media (prefers-color-scheme:dark){body{background:#0d0d0d;color:#fff} td,th{border-color:#2c2c2a} a{color:#3987e5}}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
</head><body>
<p><a href="index.html">&larr; Dashboard</a> &middot; <a href="downloads/FINDINGS.md">Markdown</a>
 &middot; <a href="downloads/semirremolques_activos.csv">semirremolques_activos.csv</a></p>
<div id="md">Cargando&hellip;</div>
<script>
fetch('downloads/FINDINGS.md').then(r => r.text()).then(t => {
  const el = document.getElementById('md');
  if (window.marked) el.innerHTML = marked.parse(t);
  else { const pre = document.createElement('pre'); pre.textContent = t; el.replaceChildren(pre); }
});
</script></body></html>
"""

NETLIFY_TOML = """# Netlify deploys the `site` branch as-is: no build step, publish the root.
[build]
  publish = "."
  command = ""

[[headers]]
  for = "/data/*"
  [headers.values]
    Cache-Control = "public, max-age=3600"

[[headers]]
  for = "/downloads/*"
  [headers.values]
    Cache-Control = "public, max-age=3600"
"""


def dump(path, obj) -> int:
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def as_table(rows: list[dict]) -> dict:
    """Array-of-arrays with a header - a third the size of a list of objects."""
    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "rows": [[r[c] for c in columns] for r in rows]}


def main() -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    (SITE / "downloads").mkdir()
    sizes: dict[str, int] = {}

    stats = dashboard._stats()
    stats["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    sizes["data/stats.json"] = dump(SITE / "data" / "stats.json", stats)
    sizes["data/charts.json"] = dump(SITE / "data" / "charts.json", dashboard._charts())
    sizes["data/provenance.json"] = dump(SITE / "data" / "provenance.json", dashboard._provenance())
    sizes["data/carriers.json"] = dump(SITE / "data" / "carriers.json",
                                       as_table(dashboard._carriers(all_rows=True)["rows"]))
    sizes["data/vehicles.json"] = dump(SITE / "data" / "vehicles.json",
                                       as_table(dashboard._vehicles(all_rows=True)["rows"]))

    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    marker = '<meta name="viewport" content="width=device-width, initial-scale=1">'
    if marker not in html:
        raise SystemExit("ui/index.html: viewport meta not found; cannot inject static mode")
    html = html.replace(marker, marker + '\n<meta name="data-mode" content="static">', 1)
    (SITE / "index.html").write_text(html, encoding="utf-8")
    (SITE / "findings.html").write_text(FINDINGS_HTML, encoding="utf-8")
    (SITE / "netlify.toml").write_text(NETLIFY_TOML, encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    for name in CSVS:
        shutil.copy2(OUT / name, SITE / "downloads" / name)
        sizes[f"downloads/{name}"] = (SITE / "downloads" / name).stat().st_size
    shutil.copy2(ROOT / "FINDINGS.md", SITE / "downloads" / "FINDINGS.md")

    total = sum(p.stat().st_size for p in SITE.rglob("*") if p.is_file())
    for k, v in sizes.items():
        print(f"[s13] {k:<40} {v / 1_048_576:>7.2f} MB")
    print(f"[s13] DONE site/ = {total / 1_048_576:.1f} MB "
          f"| semirremolques {stats['semirremolques_ar']:,} | CUIT ARCA {stats['cuits_titulares_semi_activos_arca']:,}")


if __name__ == "__main__":
    main()
