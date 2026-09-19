"""One command for the whole pipeline.

    python run_pipeline.py                 everything, in order (each stage resumes)
    python run_pipeline.py --from s7       start at a stage and run to the end
    python run_pipeline.py --only s9 s10   run just these stages
    python run_pipeline.py --with-probe    also run the optional RUTA coverage probe
    python run_pipeline.py --list          show the stages

Every stage is a standalone script in src/; this only sequences them and stops
at the first failure so a broken step can never be papered over by a later one.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

# (id, argv, what it does)
STAGES = [
    ("s1",  ["s1_empresas.py"],                    "CNRT company registry (57k)"),
    ("s5",  ["s5_operadores.py"],                  "CNRT cargo operating licences (24k)"),
    ("s3",  ["s3_parque.py"],                      "CNRT full vehicle registry (445k)"),
    ("s6",  ["s6_links.py"],                       "plate <-> owner CUIT links (900k)"),
    ("s6b", ["s6b_verify.py", "--repair"],         "verify every operator's link count vs API"),
    ("s6r", ["s6_links.py"],                       "refetch anything s6b flagged"),
    ("s2",  ["s2_flota.py"],                       "MERCOSUR permits per cargo CUIT"),
    ("s7",  ["s7_ruta.py", "--tipo=SEMIRREMOLQUE"], "RUTA constancia for every semi-trailer"),
    ("s4",  ["s4_arca.py"],                        "ARCA taxpayer padron (6.2M, downloads)"),
    ("s8",  ["s8_dnrpa.py"],                       "DNRPA national flows 2018-2026 (downloads)"),
    ("s9",  ["s9_build.py"],                       "build freight.db"),
    ("s10", ["s10_export.py"],                     "delivery CSVs"),
    ("s12", ["s12_findings.py"],                   "FINDINGS.md"),
    ("val", ["validate.py", "25"],                 "re-verify a sample against the live sources"),
]
OPTIONAL = [
    ("s11", ["s11_coverage.py", "1200", "3"],      "RUTA coverage probe (neighbour sampling)"),
]


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for sid, args, what in STAGES + OPTIONAL:
            print(f"  {sid:<4} {what:<52} {' '.join(args)}")
        return 0

    stages = list(STAGES)
    if "--with-probe" in argv:
        i = next(k for k, s in enumerate(stages) if s[0] == "s10")
        stages[i + 1:i + 1] = OPTIONAL
    if "--only" in argv:
        wanted = set(argv[argv.index("--only") + 1:])
        stages = [s for s in stages if s[0] in wanted]
    elif "--from" in argv:
        start = argv[argv.index("--from") + 1]
        ids = [s[0] for s in stages]
        if start not in ids:
            print(f"unknown stage {start!r}; use --list")
            return 2
        stages = stages[ids.index(start):]

    t0 = time.time()
    for sid, args, what in stages:
        print(f"\n{'=' * 72}\n[{sid}] {what}\n{'=' * 72}", flush=True)
        t = time.time()
        rc = subprocess.run([sys.executable, "-u", *args], cwd=SRC).returncode
        print(f"[{sid}] {'ok' if rc == 0 else f'FAILED rc={rc}'} in {time.time() - t:,.0f}s", flush=True)
        if rc != 0:
            print(f"\nstopped at {sid}; fix and re-run with: python run_pipeline.py --from {sid}")
            return rc

    print(f"\nall stages done in {(time.time() - t0) / 60:,.1f} min")
    print(f"  database : {ROOT / 'data' / 'out' / 'freight.db'}")
    print(f"  csv      : {ROOT / 'data' / 'out'}")
    print(f"  findings : {ROOT / 'FINDINGS.md'}")
    print(f"  dashboard: .venv\\Scripts\\python.exe -m uvicorn app:app --app-dir ui --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
