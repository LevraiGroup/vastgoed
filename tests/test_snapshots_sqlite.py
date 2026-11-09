"""
VA-35: SQLite-snapshots naast de JSON-snapshots.

Alles draait in een tijdelijke map met een spatie in de naam (zoals D:\\Fortunas Apps)
op zelfgemaakte rijen; data/ en output/ worden niet aangeraakt.
Alleen standaardbibliotheek plus de eigen modules van het project.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parent.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import snapshots  # noqa: E402

DAG = datetime(2026, 11, 1, 9, 30)
LATER = datetime(2026, 12, 1, 9, 30)
MB = 1024 * 1024


def rij(n: int, woonplaats: str = "Delft") -> dict:
    tekst = f"{n:016d}"
    return {
        "identificatie": tekst,
        "rdf_seealso": f"http://bag.example/{tekst}",
        "oppervlakte": n % 500,
        "status": "Verblijfsobject in gebruik",
        "gebruiksdoel": "winkelfunctie,woonfunctie",
        "openbare_ruimte": "Markt",
        "huisnummer": n % 100,
        "huisletter": "",
        "toevoeging": "",
        "postcode": "2611GS",
        "woonplaats": woonplaats,
        "bouwjaar": 1900 + n % 120,
        "pandidentificatie": f"{n // 3:016d}",
        "pandstatus": "Pand in gebruik",
        "_x": 81993.196,
        "_y": 447015.474,
    }


def rijen(aantal: int, woonplaats: str = "Delft"):
    return (rij(n, woonplaats) for n in range(aantal))


def maak_sqlite(pad: Path, meta: dict | None) -> None:
    """Een snapshot met de hand, voor de gevallen die de schrijver niet maakt."""
    with closing(sqlite3.connect(pad)) as conn:
        conn.execute("CREATE TABLE vbo (identificatie)")
        conn.execute("INSERT INTO vbo VALUES ('1')")
        if meta is not None:
            conn.execute("CREATE TABLE meta (sleutel TEXT PRIMARY KEY, waarde TEXT NOT NULL)")
            conn.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
        conn.commit()


class Basis(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="va 35 ")
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)

    def schrijf(self, rows=None, wanneer=DAG):
        rows = rijen(3) if rows is None else rows
        return snapshots.schrijf_sqlite("Delft", "delft", rows, self.data, wanneer)

    def lijst(self, **opties):
        return snapshots.lijst("Delft", "delft", self.data, {}, **opties)

    def namen(self, **opties):
        return [s.pad.name for s in self.lijst(**opties)]

    def mappen(self):
        return sorted(p.name for p in self.data.iterdir())


class SchrijvenTest(Basis):
    def test_naam_en_gegevens(self):
        snap = self.schrijf()
        self.assertEqual(snap.pad.name, "vbo_delft_2026-11-01.sqlite")
        self.assertEqual((snap.ophaaldatum, snap.volgnummer, snap.soort), ("2026-11-01", 1, "sqlite"))
        self.assertEqual(self.mappen(), ["vbo_delft_2026-11-01.sqlite"])

    def test_tweede_ingest_krijgt_volgnummer_en_laat_de_eerste_staan(self):
        eerste = self.schrijf()
        voor = eerste.pad.read_bytes()
        tweede = self.schrijf()
        self.assertEqual(tweede.pad.name, "vbo_delft_2026-11-01_2.sqlite")
        self.assertEqual(tweede.volgnummer, 2)
        self.assertEqual(eerste.pad.read_bytes(), voor)

    def test_bestaand_bestand_op_de_eerste_naam_blijft_onaangeroerd(self):
        vreemd = self.data / "vbo_delft_2026-11-01.sqlite"
        vreemd.write_bytes(b"niet van ons")
        self.assertEqual(self.schrijf().pad.name, "vbo_delft_2026-11-01_2.sqlite")
        self.assertEqual(vreemd.read_bytes(), b"niet van ons")

    def test_achtergebleven_deelbestand_blijft_onaangeroerd(self):
        deel = self.data / "vbo_delft_2026-11-01.sqlite.deel"
        deel.write_bytes(b"halve ingest")
        self.assertEqual(self.schrijf().pad.name, "vbo_delft_2026-11-01_2.sqlite")
        self.assertEqual(deel.read_bytes(), b"halve ingest")

    def test_hernoemen_overschrijft_nooit(self):
        doel = self.data / "doel.sqlite"
        doel.write_bytes(b"bestaand")
        bron = self.data / "bron.deel"
        bron.write_bytes(b"nieuw")
        with self.assertRaises(FileExistsError):
            snapshots._hernoem_exclusief(bron, doel)
        self.assertEqual(doel.read_bytes(), b"bestaand")

    def test_afgebroken_schrijven_laat_niets_bruikbaars_achter(self):
        def stuk():
            yield rij(1)
            raise ValueError("verbinding weg")

        with self.assertRaises(ValueError):
            self.schrijf(stuk())
        self.assertEqual(self.mappen(), [])
        self.assertEqual(self.lijst(), [])

    def test_onbekend_veld_gaat_niet_stilzwijgend_verloren(self):
        with self.assertRaises(snapshots.SnapshotFout):
            self.schrijf([dict(rij(1), nieuw_veld="x")])
        self.assertEqual(self.mappen(), [])

    def test_tijdens_het_schrijven_bestaat_alleen_de_tijdelijke_naam(self):
        gezien = []

        def spion():
            yield rij(1)
            gezien.append(self.mappen())
            gezien.append(self.namen())

        self.schrijf(spion())
        # Naast het .deel-bestand staat tijdens de transactie SQLite's eigen -journal.
        self.assertIn("vbo_delft_2026-11-01.sqlite.deel", gezien[0])
        self.assertEqual([n for n in gezien[0] if ".deel" not in n], [])
        self.assertEqual(gezien[1], [])

    def test_meta_wordt_als_laatste_geschreven(self):
        snap = self.schrijf()
        with closing(sqlite3.connect(snap.pad)) as conn:
            namen = [r[0] for r in conn.execute("SELECT name FROM sqlite_master ORDER BY rowid")
                     if not r[0].startswith("sqlite_")]
        self.assertEqual(namen, ["vbo", "vbo_woonplaats", "meta"])

    def test_meta_vult_de_velden_van_de_json_snapshot(self):
        snap = snapshots.schrijf_sqlite(
            "Delft", "delft", rijen(2), self.data, DAG, extra_meta={"bron": "test", "versie": 2}
        )
        meta = snapshots._lees_meta(snap.pad)
        self.assertEqual(meta["ophaaldatum"], "2026-11-01")
        self.assertEqual(meta["woonplaats"], "Delft")
        self.assertEqual(meta["aantal_vbo"], "2")
        self.assertEqual(meta["bestand"], snap.pad.name)
        self.assertEqual(meta["bron"], "test")
        self.assertEqual(meta["versie"], "2")

    def test_waarden_komen_terug_zoals_ze_erin_gingen(self):
        rijtje = [dict(rij(7), toevoeging="12", huisletter=None), rij(8)]
        snap = self.schrijf(rijtje)
        self.assertEqual(snapshots.lees(snap), rijtje)
        terug = snapshots.lees(snap)[0]
        self.assertEqual(terug["identificatie"], "0000000000000007")  # voorloopnullen
        self.assertIsInstance(terug["toevoeging"], str)
        self.assertIsInstance(terug["oppervlakte"], int)
        self.assertIsInstance(terug["_x"], float)

    def test_ontbrekend_veld_wordt_none(self):
        kort = rij(1)
        del kort["toevoeging"]
        self.assertIsNone(snapshots.lees(self.schrijf([kort]))[0]["toevoeging"])


class KiezenTest(Basis):
    def json_snapshot(self, wanneer=DAG, rows=None):
        return snapshots.schrijf("Delft", "delft", rows or [rij(1)], self.data, wanneer)

    def test_lijst_toont_json_en_sqlite_samen_van_oud_naar_nieuw(self):
        self.schrijf(wanneer=LATER)
        self.json_snapshot(DAG)
        self.assertEqual(self.namen(), ["vbo_delft_2026-11-01.json", "vbo_delft_2026-12-01.sqlite"])

    def test_op_dezelfde_dag_telt_sqlite_als_nieuwer(self):
        self.json_snapshot()
        snap = self.schrijf()
        self.assertEqual(snapshots.kies("Delft", "delft", self.data, {}), snap)

    def test_kies_op_datum_en_op_bestandsnaam(self):
        oud = self.schrijf()
        nieuw = self.schrijf(wanneer=LATER)
        kies = lambda keuze: snapshots.kies("Delft", "delft", self.data, {}, keuze)  # noqa: E731
        self.assertEqual(kies(None), nieuw)
        self.assertEqual(kies("2026-11-01"), oud)
        self.assertEqual(kies(oud.pad.name), oud)
        with self.assertRaises(snapshots.SnapshotFout):
            kies("2030-01-01")

    def test_ander_gebied_met_gelijk_begin_telt_niet_mee(self):
        snapshots.schrijf_sqlite("Den Haag", "den_haag", rijen(1), self.data, DAG)
        self.assertEqual(snapshots.lijst("Den", "den", self.data, {}), [])

    def assert_overgeslagen(self, naam):
        with mock.patch("builtins.print") as uit:
            self.assertEqual(self.namen(), [])
        self.assertIn(naam, " ".join(str(c.args[0]) for c in uit.call_args_list))

    def test_deelbestand_wordt_overgeslagen_en_gemeld(self):
        maak_sqlite(self.data / "vbo_delft_2026-11-01.sqlite.deel", {"ophaaldatum": "2026-11-01"})
        self.assert_overgeslagen("vbo_delft_2026-11-01.sqlite.deel")

    def test_andere_tijdelijke_naam_doet_niet_mee(self):
        maak_sqlite(self.data / "vbo_delft_2026-11-01.tmp", {"ophaaldatum": "2026-11-01"})
        maak_sqlite(self.data / "vbo_delft_2026-11-01.tmp.sqlite", {"ophaaldatum": "2026-11-01"})
        self.assertEqual(self.namen(), [])

    def test_zonder_meta_tabel_overgeslagen(self):
        maak_sqlite(self.data / "vbo_delft_2026-11-01.sqlite", None)
        self.assert_overgeslagen("vbo_delft_2026-11-01.sqlite")

    def test_meta_zonder_ophaaldatum_overgeslagen(self):
        maak_sqlite(self.data / "vbo_delft_2026-11-01.sqlite", {"bron": "x"})
        self.assert_overgeslagen("vbo_delft_2026-11-01.sqlite")

    def test_ophaaldatum_anders_dan_bestandsnaam_overgeslagen(self):
        maak_sqlite(self.data / "vbo_delft_2026-11-01.sqlite", {"ophaaldatum": "2026-10-01"})
        self.assert_overgeslagen("vbo_delft_2026-11-01.sqlite")

    def test_leeg_of_kapot_bestand_overgeslagen(self):
        (self.data / "vbo_delft_2026-11-01.sqlite").write_bytes(b"")
        (self.data / "vbo_delft_2026-11-02.sqlite").write_bytes(b"dit is geen database" * 100)
        self.assertEqual(self.namen(), [])

    def test_lijst_wijzigt_niets_en_laat_geen_bijbestanden_achter(self):
        snap = self.schrijf()
        voor = (snap.pad.stat().st_mtime_ns, snap.pad.read_bytes())
        self.lijst()
        self.assertEqual((snap.pad.stat().st_mtime_ns, snap.pad.read_bytes()), voor)
        self.assertEqual(self.mappen(), [snap.pad.name])

    def test_ophaaldatum_lezen_opent_de_datarijen_niet(self):
        self.schrijf()
        echt = sqlite3.connect
        statements: list[str] = []

        def met_trace(*args, **kwargs):
            conn = echt(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        with mock.patch.object(snapshots.sqlite3, "connect", met_trace):
            self.assertEqual(len(self.lijst()), 1)
        self.assertTrue(statements)
        self.assertFalse([s for s in statements if "from vbo" in s.lower()], statements)


class JsonOngewijzigdTest(Basis):
    def test_json_schrijven_en_lezen_blijft_hetzelfde(self):
        rows = [rij(1), rij(2)]
        snap = snapshots.schrijf("Delft", "delft", rows, self.data, DAG)
        self.assertEqual(snap.pad.name, "vbo_delft_2026-11-01.json")
        self.assertEqual(snap.soort, "json")
        self.assertEqual(snap.pad.read_text(encoding="utf-8"), json.dumps(rows, ensure_ascii=False))
        self.assertEqual(snapshots.lees(snap), rows)
        self.assertEqual(list(snapshots.stroom(snap)), rows)
        self.assertEqual(self.mappen(), ["vbo_delft_2026-11-01.json", "vbo_delft_2026-11-01.meta.json"])

    def test_oude_snapshot_uit_de_config_werkt_nog(self):
        oud = self.data / "vbo_delft.json"
        oud.write_text("[]", encoding="utf-8")
        cfg = {"snapshots": {"ongedateerd": {"vbo_delft.json": "2026-08-04"}}}
        self.assertEqual(
            snapshots.lijst("Delft", "delft", self.data, cfg),
            [snapshots.Snapshot("Delft", oud, "2026-08-04", 0, "config")],
        )


class LandelijkTest(Basis):
    @staticmethod
    def nl_rij(n: int) -> dict:
        if n % 2 == 0:
            return dict(rij(n, "Delft"), woonplaats_identificatie="2138")
        return dict(rij(n, "Rotterdam"), woonplaats_identificatie="3086")

    def landelijk(self, wanneer=DAG):
        return snapshots.schrijf_landelijk(
            (self.nl_rij(n) for n in range(6)), self.data, wanneer
        )

    def test_naam_en_volgnummer(self):
        self.assertEqual(self.landelijk().pad.name, "bag_nl_2026-11-01.sqlite")
        self.assertEqual(self.landelijk().pad.name, "bag_nl_2026-11-01_2.sqlite")

    def test_standaardkeuze_van_een_gebied_verandert_niet(self):
        eigen = self.schrijf()
        self.landelijk(LATER)
        self.assertEqual(self.lijst(), [eigen])
        self.assertEqual(snapshots.kies("Delft", "delft", self.data, {}), eigen)

    def test_kiezen_met_vlag_en_met_bestandsnaam(self):
        self.schrijf()
        nl = self.landelijk(LATER)
        keuze = snapshots.kies("Delft", "delft", self.data, {}, landelijk=True)
        self.assertEqual((keuze.pad, keuze.woonplaats, keuze.landelijk), (nl.pad, "Delft", True))
        keuze = snapshots.kies("Delft", "delft", self.data, {}, nl.pad.name)
        self.assertEqual((keuze.pad, keuze.landelijk), (nl.pad, True))

    def test_deelbestand_wordt_overgeslagen(self):
        (self.data / "bag_nl_2026-11-01.sqlite.deel").write_bytes(b"")
        with mock.patch("builtins.print") as uit:
            self.assertEqual(self.lijst(landelijk=True), [])
        uit.assert_called_once()

    def test_stroom_geeft_een_gebied_in_ingestvolgorde(self):
        self.landelijk()
        snap = snapshots.kies("Delft", "delft", self.data, {}, landelijk=True)
        verwacht = [self.nl_rij(n) for n in (0, 2, 4)]
        self.assertEqual(list(snapshots.stroom(snap)), verwacht)
        self.assertEqual(snapshots.lees(snap), verwacht)

    def test_nederland_geeft_alles(self):
        self.assertEqual(len(list(snapshots.stroom(self.landelijk()))), 6)

    def test_gebied_gebruikt_de_index(self):
        snap = self.landelijk()
        with closing(sqlite3.connect(snap.pad)) as conn:
            plan = " ".join(
                r[3]
                for r in conn.execute(
                    'EXPLAIN QUERY PLAN SELECT * FROM vbo WHERE "woonplaats_naam" = ? ORDER BY rowid',
                    ("Delft",),
                )
            )
        self.assertIn("vbo_woonplaats", plan)
        self.assertNotIn("TEMP B-TREE", plan)

    def test_onbekend_gebied_is_een_fout_geen_lege_lijst(self):
        self.landelijk()
        snap = snapshots.kies("Atlantis", "atlantis", self.data, {}, landelijk=True)
        with self.assertRaises(snapshots.SnapshotFout):
            list(snapshots.stroom(snap))

    def test_halverwege_stoppen_sluit_het_bestand(self):
        snap = self.landelijk()
        loper = snapshots.stroom(snap)
        next(loper)
        loper.close()
        snap.pad.rename(snap.pad.with_suffix(".verplaatst"))  # lukt op Windows alleen als het dicht is


class DubbeleNaamTest(Basis):
    """VA-33: 70 woonplaatsnamen komen meer dan eens voor, bijvoorbeeld Beek."""

    def setUp(self):
        super().setUp()
        rows = [
            dict(rij(1, "Beek"), woonplaats_identificatie="1001"),
            dict(rij(2, "Beek"), woonplaats_identificatie="1002"),
            dict(rij(3, "Delft"), woonplaats_identificatie="2138"),
        ]
        self.rows = rows
        self.snap = snapshots.schrijf_landelijk(iter(rows), self.data, DAG)

    def gekozen(self, naam):
        return snapshots.kies(naam, naam.lower(), self.data, {}, landelijk=True)

    def test_dubbele_naam_stopt_en_noemt_de_woonplaatsen(self):
        with self.assertRaisesRegex(snapshots.SnapshotFout, "1001, 1002"):
            list(snapshots.stroom(self.gekozen("Beek")))

    def test_met_woonplaats_id_komt_alleen_die_plaats_terug(self):
        rows = list(snapshots.stroom(self.gekozen("Beek"), woonplaats_id="1002"))
        self.assertEqual(rows, [self.rows[1]])

    def test_woonplaats_id_werkt_ook_op_heel_nederland(self):
        self.assertEqual(list(snapshots.stroom(self.snap, woonplaats_id="2138")), [self.rows[2]])

    def test_unieke_naam_werkt_zonder_id(self):
        self.assertEqual(list(snapshots.stroom(self.gekozen("Delft"))), [self.rows[2]])

    def test_onbekend_id_is_een_fout(self):
        with self.assertRaises(snapshots.SnapshotFout):
            list(snapshots.stroom(self.snap, woonplaats_id="9999"))

    def test_id_gebruikt_de_index_zonder_te_sorteren(self):
        with closing(sqlite3.connect(self.snap.pad)) as conn:
            plan = " ".join(
                r[3]
                for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM vbo "
                    'WHERE "woonplaats_identificatie" = ? ORDER BY rowid',
                    ("2138",),
                )
            )
        self.assertIn("vbo_woonplaats_id", plan)
        self.assertNotIn("TEMP B-TREE", plan)

    def test_json_snapshot_kent_geen_woonplaats_id(self):
        snap = snapshots.schrijf("Delft", "delft", [rij(1)], self.data, DAG)
        with self.assertRaises(snapshots.SnapshotFout):
            list(snapshots.stroom(snap, woonplaats_id="2138"))


class GpkgIndelingTest(Basis):
    """De bevestigde kolomnamen van VA-33 (docs/gpkg_schema.md)."""

    def test_afwijkende_namen_komen_als_pijplijnvelden_terug(self):
        snap = snapshots.schrijf_landelijk(
            [dict(rij(1), woonplaats_identificatie="2138")], self.data, DAG
        )
        with closing(sqlite3.connect(snap.pad)) as conn:
            kolommen = {r[1] for r in conn.execute("PRAGMA table_info(vbo)")}
        self.assertTrue({"pand_identificatie", "openbare_ruimte_naam", "woonplaats_naam"} <= kolommen)
        self.assertFalse({"pandidentificatie", "openbare_ruimte"} & kolommen)
        terug = next(snapshots.stroom(snap))
        self.assertEqual(terug["pandidentificatie"], rij(1)["pandidentificatie"])
        self.assertEqual(terug["openbare_ruimte"], "Markt")
        self.assertEqual(terug["woonplaats"], "Delft")

    def test_elk_veld_van_de_pijplijn_heeft_een_kolom(self):
        self.assertTrue(snapshots.KOLOMMEN_STANDAARD.keys() <= snapshots.KOLOMMEN_GPKG.keys())


class KolomindelingTest(Basis):
    INDELING = {"identificatie": "ID", "woonplaats": "PLAATS naam", "gebruiksdoel": "doel"}
    RIJ = {"identificatie": "01", "woonplaats": "Delft", "gebruiksdoel": "woonfunctie"}

    def schrijf_anders(self):
        return snapshots.schrijf_landelijk([self.RIJ], self.data, DAG, kolommen=self.INDELING)

    def test_indeling_uit_meta(self):
        self.assertEqual(list(snapshots.stroom(self.schrijf_anders())), [self.RIJ])

    def test_indeling_filtert_op_de_juiste_kolom(self):
        self.schrijf_anders()
        snap = snapshots.kies("Delft", "delft", self.data, {}, landelijk=True)
        self.assertEqual(list(snapshots.stroom(snap)), [self.RIJ])

    def test_opgegeven_indeling_gaat_voor(self):
        rows = list(snapshots.stroom(self.schrijf_anders(), kolommen={"doel_veld": "doel"}))
        self.assertEqual(rows, [{"doel_veld": "woonfunctie"}])

    def test_snapshot_zonder_indeling_gebruikt_de_kolomnamen(self):
        pad = self.data / "vbo_delft_2026-11-01.sqlite"
        maak_sqlite(pad, {"ophaaldatum": "2026-11-01"})
        self.assertEqual(snapshots.lees(self.lijst()[0]), [{"identificatie": "1"}])

    def test_onbekende_kolom_is_een_fout_geen_tekst(self):
        # SQLite leest een onbekende "naam" anders als de letterlijke tekst 'naam'.
        with self.assertRaises(snapshots.SnapshotFout):
            list(snapshots.stroom(self.schrijf_anders(), kolommen={"veld": "bestaat_niet"}))

    def test_gebied_filteren_zonder_woonplaatskolom_is_een_fout(self):
        self.schrijf_anders()
        snap = snapshots.kies("Delft", "delft", self.data, {}, landelijk=True)
        with self.assertRaises(snapshots.SnapshotFout):
            list(snapshots.stroom(snap, kolommen={"identificatie": "ID"}))


PIEK_SCRIPT = r"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import snapshots


def piek_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Teller(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("fouten", wintypes.DWORD),
                        ("piek", ctypes.c_size_t), ("rest", ctypes.c_size_t * 7)]

        teller = Teller()
        teller.cb = ctypes.sizeof(Teller)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(teller), teller.cb):
            raise ctypes.WinError()
        return teller.piek
    import resource
    factor = 1 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * factor


def rijen(aantal):
    for n in range(aantal):
        yield {"identificatie": f"{n:016d}", "woonplaats": "Delft", "gebruiksdoel": "woonfunctie",
               "openbare_ruimte": "Een straatnaam van gemiddelde lengte", "postcode": "2611GS",
               "huisnummer": n % 100, "oppervlakte": n % 500, "_x": 81993.196, "_y": 447015.474}


soort, map_, aantal = sys.argv[2], Path(sys.argv[3]), int(sys.argv[4])
if soort == "schrijf":
    snap = snapshots.schrijf_landelijk(rijen(aantal), map_, datetime(2026, 11, 1))
    gezien = aantal
else:
    snap = snapshots.Snapshot("Nederland", map_ / "bag_nl_2026-11-01.sqlite", "2026-11-01", 1,
                              "meta", "sqlite", True)
    gezien = sum(1 for _ in snapshots.stroom(snap))
print(gezien, piek_bytes())
"""


class GeheugenTest(Basis):
    """Echte procespiek in een eigen proces, dus inclusief SQLite's eigen geheugen.

    tracemalloc ziet alleen Python-objecten en vertraagt 1M rijen tot minuten; het
    meet hier alleen het lezen van 200k rijen.
    """

    def proces(self, soort: str, aantal: int) -> tuple[int, int]:
        klaar = subprocess.run(
            [sys.executable, "-c", PIEK_SCRIPT, str(PROJECT), soort, str(self.data), str(aantal)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(klaar.returncode, 0, klaar.stderr)
        gezien, piek = klaar.stdout.split()
        return int(gezien), int(piek)

    def test_schrijven_van_1m_rijen_houdt_ze_niet_vast(self):
        gezien, piek = self.proces("schrijf", 1_000_000)
        print(f"VA-35 schrijver, 1.000.000 rijen: procespiek {piek / MB:.1f} MB")
        self.assertEqual(gezien, 1_000_000)
        # Criterium: onder 500 MB. Strenger, want alle rijen vasthouden blijft daar ook onder.
        self.assertLess(piek, 100 * MB, f"piek {piek / MB:.1f} MB")
        pad = self.data / "bag_nl_2026-11-01.sqlite"
        with closing(sqlite3.connect(pad)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM vbo").fetchone()[0], 1_000_000)

    def test_stroom_van_200k_rijen_houdt_ze_niet_vast(self):
        self.proces("schrijf", 200_000)
        gezien, piek = self.proces("stroom", 200_000)
        print(f"VA-35 stroom, 200.000 rijen: procespiek {piek / MB:.1f} MB")
        self.assertEqual(gezien, 200_000)
        self.assertLess(piek, 60 * MB, f"piek {piek / MB:.1f} MB")

        snap = snapshots.Snapshot(
            "Nederland", self.data / "bag_nl_2026-11-01.sqlite", "2026-11-01", 1, "meta", "sqlite", True
        )
        tracemalloc.start()
        try:
            teller = sum(1 for _ in snapshots.stroom(snap))
            python_piek = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        print(f"VA-35 stroom, 200.000 rijen: tracemalloc-piek {python_piek / MB:.2f} MB")
        self.assertEqual(teller, 200_000)
        self.assertLess(python_piek, 5 * MB, f"piek {python_piek / MB:.2f} MB")


if __name__ == "__main__":
    unittest.main()
