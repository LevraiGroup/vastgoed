"""
Regressiesuite voor de Delft-cijfers van het goedgekeurde proefresultaat (augustus 2026).

Een wijziging die een Delft-cijfer verschuift, laat hier een test falen. De suite
roept selectie.verwerk() direct aan en vergelijkt het resultaat in het geheugen; hij
draait run_proef.py NIET en schrijft dus niets in output/ of data/. Dat wordt ook
gecontroleerd: de wijzigingstijden en groottes van de bestanden die de pijplijn kan
schrijven of nooit mag aanraken (BEWAAKTE_PATRONEN) zijn voor en na gelijk. Andere
bestanden, zoals de GeoPackage-download in data/bron/, tellen niet mee (VA-44).

De suite leest expliciet de augustus-snapshot data/vbo_delft.json en niet de
nieuwste (de standaard sinds VA-3), zodat een latere ingest de vastgepinde cijfers
niet verschuift. Zonder dat bestand (bijvoorbeeld een verse kloon zonder data/)
worden de cijfertests overgeslagen met een melding die het bestand noemt.

Alleen standaardbibliotheek plus de eigen modules van het project.
"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import selectie  # noqa: E402

AUGUSTUS_SNAPSHOT = "vbo_delft.json"  # ongedateerd bestand, opgehaald 2026-08-04
VBO_DELFT = PROJECT / "data" / AUGUSTUS_SNAPSHOT
MASTER_CSV = PROJECT / "output" / "mastervoorraad_delft.csv"
# Wat de pijplijn kan schrijven of nooit mag aanraken (VA-44). Patronen zijn niet
# recursief: data/bron/ (de GeoPackage-download) en andere bestanden vallen erbuiten.
# data/vbo_*.json dekt ook vbo_*.meta.json; panden_*.json ook panden_*.bron.json.
BEWAAKTE_PATRONEN = (
    "output/*.csv",
    "data/vbo_*.json",
    "data/vbo_*.meta.json",
    "data/panden_*.json",
    "data/verrijking_*.json",
    "data/*.bron.json",
)

# Vastgepinde cijfers (README "Resultaat Delft", PROJECT.md "Tests").
# Werklijst: 1.668 is wat de code, de gecommitte mastervoorraad_delft.csv en het
# gecommitte dashboard (design/index.html) alle drie geven. De README noemt nog 1.655;
# dat is het aantal zonder het signaal verbouwing_bag (+2) en dateert van voor dat
# signaal. VA-11 corrigeert de README (zie LESSONS.md).
VERWACHT = {
    "vbo": 61_993,
    "panden": 24_008,
    "uitgesloten": 1_314,
    "in_categorie": 2_346,
    "per_categorie": {"A": 348, "B": 322, "C": 1_322, "D": 562, "E": 360},
    "werklijst_drempel": 8,
    "werklijst": 1_668,
}


def momentopname(basis: Path = PROJECT, patronen=BEWAAKTE_PATRONEN) -> dict[str, tuple[int, int]]:
    """Pad -> (mtime_ns, grootte) voor elk bestand onder basis dat op een patroon past."""
    stand: dict[str, tuple[int, int]] = {}
    for patroon in patronen:
        for pad in basis.glob(patroon):
            if pad.is_file():
                st = pad.stat()
                stand[pad.relative_to(basis).as_posix()] = (st.st_mtime_ns, st.st_size)
    return stand


def lees_master_csv() -> list[dict]:
    with open(MASTER_CSV, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


@unittest.skipUnless(
    VBO_DELFT.exists(),
    f"{VBO_DELFT.relative_to(PROJECT)} ontbreekt: de Delft-cijfertests hebben de "
    "augustusdata nodig (niet in git)",
)
class TestDelftCijfers(unittest.TestCase):
    """De cijfers uit de README-tabel en de mastervoorraad, regel voor regel."""

    @classmethod
    def setUpClass(cls):
        cls.voor = momentopname()
        cls.cfg = selectie.load_config()
        cls.panden = selectie.verwerk(
            ["Delft"], cls.cfg, "Delft", snapshot=AUGUSTUS_SNAPSHOT
        )
        cls.actief = [p for p in cls.panden if not p["uitgesloten"]]
        cls.in_cat = [p for p in cls.actief if p["categorieen"]]
        # Zelfde volgorde als run_proef.py voor de mastervoorraad.
        cls.master = sorted(cls.in_cat, key=lambda p: (-p["leadscore"], p["bag_pand_id"]))
        cls.csv_rijen = lees_master_csv() if MASTER_CSV.exists() else None
        cls.na = momentopname()

    def test_aantal_vbo(self):
        self.assertEqual(sum(p["aantal_vbo"] for p in self.panden), VERWACHT["vbo"])

    def test_aantal_unieke_panden(self):
        self.assertEqual(len(self.panden), VERWACHT["panden"])

    def test_aantal_uitgesloten(self):
        self.assertEqual(len(self.panden) - len(self.actief), VERWACHT["uitgesloten"])

    def test_aantal_binnen_categorie_a_tot_e(self):
        self.assertEqual(len(self.in_cat), VERWACHT["in_categorie"])

    def test_aantal_per_categorie(self):
        for cat, verwacht in VERWACHT["per_categorie"].items():
            with self.subTest(categorie=cat):
                n = sum(1 for p in self.actief if cat in p["categorieen"])
                self.assertEqual(n, verwacht)

    def test_werklijstdrempel_in_config(self):
        self.assertEqual(
            self.cfg["drempels"]["score_min_voor_werklijst"], VERWACHT["werklijst_drempel"]
        )

    def test_aantal_werklijst(self):
        drempel = self.cfg["drempels"]["score_min_voor_werklijst"]
        n = sum(1 for p in self.in_cat if p["leadscore"] >= drempel)
        self.assertEqual(n, VERWACHT["werklijst"])

    def _vereis_csv(self):
        if self.csv_rijen is None:
            self.skipTest(f"{MASTER_CSV.relative_to(PROJECT)} ontbreekt")

    def test_master_bag_pand_id_volgorde_gelijk_aan_csv(self):
        self._vereis_csv()
        self.assertEqual(
            [p["bag_pand_id"] for p in self.master],
            [r["bag_pand_id"] for r in self.csv_rijen],
        )

    def test_master_leadscore_per_rij_gelijk_aan_csv(self):
        self._vereis_csv()
        self.assertEqual(
            [str(p["leadscore"]) for p in self.master],
            [r["leadscore"] for r in self.csv_rijen],
        )

    def test_master_categorieen_per_rij_gelijk_aan_csv(self):
        self._vereis_csv()
        # run_proef.py schrijft lijsten als 'A | C | E'.
        self.assertEqual(
            [" | ".join(p["categorieen"]) for p in self.master],
            [r["categorieen"] for r in self.csv_rijen],
        )

    def test_output_en_data_onaangeroerd(self):
        self.assertTrue(self.voor, "momentopname ziet geen enkel bewaakt bestand")
        self.assertEqual(self.voor, self.na)


class TestMomentopnameBewaakt(unittest.TestCase):
    """Welke bestanden de onaangeroerd-controle bewaakt (VA-44); zonder data."""

    def test_bewaakt_pijplijnbestanden_en_negeert_de_rest(self):
        bewaakt = {
            "output/mastervoorraad_delft.csv",
            "output/werklijst_delft_2026-08.csv",
            "data/vbo_delft.json",
            "data/vbo_delft_2026-11-06.json",
            "data/vbo_delft_2026-11-06.meta.json",
            "data/panden_delft.json",
            "data/panden_delft.bron.json",
            "data/verrijking_delft.json",
        }
        genegeerd = {
            "data/bron/bag-light_2026-11-01.gpkg",
            "data/bron/vbo_delft.json",
            "data/notitie.txt",
            "output/dashboard.html",
        }
        with tempfile.TemporaryDirectory() as tmp:
            basis = Path(tmp)
            for rel in bewaakt | genegeerd:
                pad = basis / rel
                pad.parent.mkdir(parents=True, exist_ok=True)
                pad.write_text("x", encoding="utf-8")
            self.assertEqual(set(momentopname(basis)), bewaakt)


if __name__ == "__main__":
    unittest.main()
