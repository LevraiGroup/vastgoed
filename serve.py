"""
Serveert het dashboard (design/) op Railway, alleen met de standaardbibliotheek.

De poort komt uit de omgevingsvariabele PORT (Railway zet die); lokaal is het 8000.
De server toont alleen wat in design/ staat: data/, output/ en de code blijven buiten
bereik. De pipeline (ingest.py, verrijk.py, run_proef.py) draait hier nooit.

    python serve.py            # http://localhost:8000/
"""
from __future__ import annotations

import functools
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DESIGN = Path(__file__).resolve().parent / "design"
STANDAARD_POORT = 8000


def poort_uit_omgeving(omgeving: dict[str, str] | None = None) -> int:
    """De poort uit PORT, of 8000. Een ongeldige waarde stopt met een duidelijke fout."""
    waarde = (omgeving if omgeving is not None else os.environ).get("PORT", "").strip()
    if not waarde:
        return STANDAARD_POORT
    try:
        poort = int(waarde)
    except ValueError:
        raise SystemExit(f"FOUT: PORT moet een getal zijn, niet {waarde!r}") from None
    if not 0 < poort < 65536:
        raise SystemExit(f"FOUT: PORT {poort} ligt buiten 1-65535")
    return poort


def maak_server(poort: int, host: str = "0.0.0.0",
                map_: Path = DESIGN) -> ThreadingHTTPServer:
    """Een server die alleen `map_` serveert."""
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(map_))
    return ThreadingHTTPServer((host, poort), handler)


def main() -> int:
    if not (DESIGN / "index.html").is_file():
        print(f"FOUT: {DESIGN / 'index.html'} ontbreekt", file=sys.stderr)
        return 1
    poort = poort_uit_omgeving()
    server = maak_server(poort)
    print(f"Dashboard op poort {poort}, map {DESIGN}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
