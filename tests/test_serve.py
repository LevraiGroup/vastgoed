"""
VA-46: serve.py serveert design/ op de poort uit PORT, en niets daarbuiten.
Alleen standaardbibliotheek, alleen localhost, geen netwerk naar buiten.
"""
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import serve  # noqa: E402


class Poort(unittest.TestCase):
    def test_standaard_8000(self):
        self.assertEqual(serve.poort_uit_omgeving({}), 8000)
        self.assertEqual(serve.poort_uit_omgeving({"PORT": " "}), 8000)

    def test_uit_port(self):
        self.assertEqual(serve.poort_uit_omgeving({"PORT": "8080"}), 8080)

    def test_ongeldig_stopt(self):
        for waarde in ("$PORT", "abc", "0", "70000"):
            with self.subTest(waarde=waarde), self.assertRaises(SystemExit):
                serve.poort_uit_omgeving({"PORT": waarde})


class Serveert(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.design = root / "design"
        self.design.mkdir()
        self.index = "<!doctype html><title>Dashboard</title>1.668".encode("utf-8")
        (self.design / "index.html").write_bytes(self.index)
        (root / "data").mkdir()
        (root / "data" / "vbo_delft.json").write_text("{}", encoding="utf-8")

        self.server = serve.maak_server(0, host="127.0.0.1", map_=self.design)
        self.addCleanup(self.server.server_close)
        t = threading.Thread(target=self.server.serve_forever, daemon=True)
        t.start()
        self.addCleanup(self.server.shutdown)
        self.basis = f"http://127.0.0.1:{self.server.server_address[1]}"

    def haal(self, pad):
        with urllib.request.urlopen(self.basis + pad, timeout=5) as r:
            return r.status, r.read()

    def test_root_is_index(self):
        status, body = self.haal("/")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.index)

    def test_buiten_design_niet_bereikbaar(self):
        for pad in ("/data/vbo_delft.json", "/../data/vbo_delft.json",
                    "/%2e%2e/data/vbo_delft.json"):
            with self.subTest(pad=pad):
                with self.assertRaises(urllib.error.HTTPError) as fout:
                    self.haal(pad)
                self.assertEqual(fout.exception.code, 404)
                fout.exception.close()


if __name__ == "__main__":
    unittest.main()
