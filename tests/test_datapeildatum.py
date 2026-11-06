"""
VA-4: de datapeildatum van een lead is de ophaaldatum van zijn data, niet de datum
waarop het script draaide.

De eenheidstests bouwen kleine nep-snapshots in een tijdelijke map en geven ze via
verwerk(gekozen=...) mee, dus ze lezen en schrijven niets in data/ of output/. De
Delft-test leest de augustus-snapshot data/vbo_delft.json en wordt overgeslagen als
dat bestand ontbreekt.

Alleen standaardbibliotheek plus de eigen modules van het project.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import selectie  # noqa: E402
from snapshots import Snapshot, SnapshotFout  # noqa: E402

VBO_DELFT = PROJECT / "data" / "vbo_delft.json"
# Een label zonder verrijkingsbestand in data/, zodat laad_verrijking() niets vindt.
TESTLABEL = "VA4 testgebied"


def vbo(identificatie: str, pand_id: str, woonplaats: str) -> dict:
    return {
        "identificatie": identificatie,
        "pandidentificatie": pand_id,
        "woonplaats": woonplaats,
        "gebruiksdoel": "winkelfunctie,woonfunctie",
        "oppervlakte": 80,
        "bouwjaar": 1930,
        "pandstatus": "Pand in gebruik",
        "status": "Verblijfsobject in gebruik",
        "openbare_ruimte": "Teststraat",
        "huisnummer": 1,
        "postcode": "1234AB",
    }


class TestPeildatumUitSnapshot(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.map = Path(self._tmp.name)
        self.cfg = selectie.load_config()

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, woonplaats: str, naam: str, datum, rows: list[dict]) -> Snapshot:
        pad = self.map / naam
        pad.write_text(json.dumps(rows), encoding="utf-8")
        bron = "meta" if datum else "onbekend"
        return Snapshot(woonplaats, pad, datum, 1, bron)

    def test_elk_pand_draagt_de_datum_van_zijn_eigen_woonplaats(self):
        a = self.snapshot("Aplaats", "vbo_aplaats_2026-08-04.json", "2026-08-04", [
            vbo("A1", "P-A-0000000001", "Aplaats"),
            vbo("A2", "P-A-0000000001", "Aplaats"),
            vbo("A3", "P-A-0000000002", "Aplaats"),
        ])
        b = self.snapshot("Bplaats", "vbo_bplaats_2026-10-01.json", "2026-10-01", [
            vbo("B1", "P-B-0000000003", "Bplaats"),
        ])
        panden = selectie.verwerk(["Aplaats", "Bplaats"], self.cfg, TESTLABEL, gekozen=[a, b])
        per_pand = {p["bag_pand_id"]: p["datapeildatum"] for p in panden}
        self.assertEqual(per_pand, {
            "P-A-0000000001": "2026-08-04",
            "P-A-0000000002": "2026-08-04",
            "P-B-0000000003": "2026-10-01",
        })
        self.assertNotIn(date.today().isoformat(), per_pand.values())

    def test_snapshot_zonder_ophaaldatum_stopt_met_de_bestandsnaam(self):
        goed = self.snapshot("Aplaats", "vbo_aplaats_2026-08-04.json", "2026-08-04",
                             [vbo("A1", "P-A-0000000001", "Aplaats")])
        zonder = self.snapshot("Rijswijk", "vbo_rijswijk.json", None,
                               [vbo("R1", "P-R-0000000001", "Rijswijk")])
        with self.assertRaises(SnapshotFout) as ctx:
            selectie.verwerk(["Aplaats", "Rijswijk"], self.cfg, TESTLABEL, gekozen=[goed, zonder])
        melding = str(ctx.exception)
        self.assertIn("vbo_rijswijk.json", melding)
        self.assertIn("geen vastgelegde ophaaldatum", melding)


@unittest.skipUnless(
    VBO_DELFT.exists(),
    f"{VBO_DELFT.relative_to(PROJECT)} ontbreekt: deze test heeft de augustusdata nodig "
    "(niet in git)",
)
class TestDelftAugustus(unittest.TestCase):

    def test_alle_delftse_panden_hebben_peildatum_4_augustus(self):
        cfg = selectie.load_config()
        panden = selectie.verwerk(["Delft"], cfg, "Delft", snapshot="vbo_delft.json")
        self.assertEqual({p["datapeildatum"] for p in panden}, {"2026-08-04"})


if __name__ == "__main__":
    unittest.main()
