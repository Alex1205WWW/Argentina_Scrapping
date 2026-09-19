"""Stage 2 - pull the cargo fleet held by every CUIT found in stage 1.

/api/vehiculo_cargas_habilitadospordocumento/{tipodoc}/{nrodoc}.json returns the
vehicles (tractors, semi-trailers, trucks, acoplados) a carrier has registered
with CNRT together with its MERCOSUR permits, so this is the plate <-> CUIT link.
"""
from __future__ import annotations

import asyncio
import json

from common import CNRT_API, UNRESOLVED, Jsonl, RAW, client, get_json

CONCURRENCY = 12
IN_EMPRESAS = RAW / "empresas.jsonl"
IN_OPERADORES = RAW / "operadores_cargas.jsonl"
OUTFILE = RAW / "flota.jsonl"


def load_docs() -> list[tuple[str, str]]:
    """Distinct (tipo_documento, CUIT) pairs to query for a cargo fleet.

    Prefers the freight-operator list from stage 5: only companies holding a
    CARGAS licence can have a cargo fleet, so sweeping the full 54k-company
    registry would spend ~90% of its requests on documented 404s.
    """
    src = IN_OPERADORES if IN_OPERADORES.exists() else IN_EMPRESAS
    seen: dict[str, tuple[str, str]] = {}
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            nro = (r.get("cuit") or "").strip()
            tipo = (r.get("tipo_documento") or "CUIT").strip()
            if nro and tipo:
                seen[f"{tipo}/{nro}"] = (tipo, nro)
    return list(seen.values())


async def main() -> None:
    docs = load_docs()
    with Jsonl(OUTFILE, "_key") as sink:
        done = sink.done_keys()
        todo = [(t, n) for (t, n) in docs if f"{t}/{n}" not in done]
        print(f"[s2] distinct docs {len(docs)} | done {len(done)} | to fetch {len(todo)}", flush=True)

        sem = asyncio.Semaphore(CONCURRENCY)
        processed = veh = withfleet = 0
        lock = asyncio.Lock()

        async with client(limit=CONCURRENCY) as cli:
            async def one(tipo: str, nro: str) -> None:
                nonlocal processed, veh, withfleet
                url = f"{CNRT_API}/vehiculo_cargas_habilitadospordocumento/{tipo}/{nro}.json"
                async with sem:
                    data = await get_json(cli, url)
                if data is UNRESOLVED:
                    return  # unrecorded, so a resume retries this CUIT
                async with lock:
                    processed += 1
                    key = f"{tipo}/{nro}"
                    if isinstance(data, list) and data:
                        sink.write({"_key": key, "tipo_documento": tipo,
                                    "nro_documento": nro, "vehiculos": data})
                        veh += len(data)
                        withfleet += 1
                    else:
                        sink.write({"_key": key, "_miss": True})
                    if processed % 500 == 0:
                        sink.flush()
                        print(f"[s2] {processed}/{len(todo)} | carriers w/fleet {withfleet} | vehicles {veh}", flush=True)

            await asyncio.gather(*(one(t, n) for t, n in todo))

    print(f"[s2] DONE processed={processed} carriers_with_fleet={withfleet} vehicles={veh} -> {OUTFILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
