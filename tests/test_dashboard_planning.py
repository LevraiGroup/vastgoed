"""
VA-86: bovenaan het Kantoor, in een glazen runpaneel in de band: van welke maand de laatste run is, wanneer
de volgende is (handmatig of automatisch), hoe ver de maand was toen de pagina gebouwd werd, en of er een
dagelijkse controle draait. De maand komt uit de naam van het nieuwste werklijstbestand, het schema uit
config.yaml (planning). Geen data nodig: de werklijstbestanden zijn lege bestanden in een tijdelijke map.
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))
sys.path.insert(0, str(HIER))

import build_dashboard as bd  # noqa: E402
from selectie import load_config  # noqa: E402
from test_dashboard_nederland import TOTALEN, cfg, pand  # noqa: E402

DAG = date(2026, 11, 16)   # een vaste bouwdag voor de tests


def plan(wijze="handmatig", dag=None, actief=False, tijd=None):
    return {"planning": {"maandrun": {"wijze": wijze, "dag": dag}, "dagcontrole": {"actief": actief, "tijd": tijd}}}


def woorden(t):
    return " ".join(v for v in t.values() if isinstance(v, str))


class MetMap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.map = Path(self._tmp.name)

    def werklijst(self, *namen):
        for n in namen:
            (self.map / n).write_text("", encoding="utf-8")

    def teksten(self, c, gebied="nederland"):
        return bd.planning_teksten(c, gebied, self.map, vandaag=DAG)


class DrieWijzen(MetMap):
    """Crit. 3: een build voor elk van de drie gevallen; 'automatisch' alleen bij wijze: automatisch."""

    def setUp(self):
        super().setUp()
        self.werklijst("werklijst_nederland_2026-10.csv", "werklijst_nederland_2026-11.csv")

    def test_handmatig_zonder_dag(self):
        t, let = self.teksten(plan())
        self.assertEqual((t["laatste"], t["volgende"], t["wijze"]), ("november 2026", "begin december 2026", "handmatig"))
        self.assertEqual(t["zin"], "Volgende run: begin december 2026, handmatig. Dagelijkse controle nog niet actief.")
        self.assertEqual(let, [])

    def test_handmatig_met_dag(self):
        t, _ = self.teksten(plan(dag=3))
        self.assertEqual((t["volgende"], t["wijze"]), ("rond 3 december 2026", "handmatig"))

    def test_automatisch(self):
        t, _ = self.teksten(plan(wijze="automatisch", dag=3))
        self.assertEqual((t["volgende"], t["wijze"], t["automatisch"]), ("3 december 2026", "automatisch", True))
        self.assertNotIn("handmatig", woorden(t))

    def test_automatisch_alleen_bij_automatisch(self):
        for c in (plan(), plan(dag=5), plan(wijze="Automatisch"), plan(wijze="automatisch"), {}):
            t, _ = self.teksten(c)
            self.assertNotRegex(woorden(t).lower(), r"automatisch|vanzelf|zelf gestart|gepland")
            self.assertFalse(t["automatisch"])

    def test_over_de_jaargrens(self):
        self.werklijst("werklijst_nederland_2026-12.csv")
        t, _ = self.teksten(plan())
        self.assertEqual((t["laatste"], t["volgende"]), ("december 2026", "begin januari 2027"))


class Voortgang(unittest.TestCase):
    """De dunne lijn door de maand: berekend in Python op de bouwdag, nooit door een klok in de browser."""

    def test_door_de_maand(self):
        self.assertEqual(bd.maand_voortgang("2026-11", date(2026, 11, 1)), 0)
        self.assertEqual(bd.maand_voortgang("2026-11", date(2026, 11, 16)), 50)
        self.assertEqual(bd.maand_voortgang("2026-12", date(2027, 1, 1)), 100)
        self.assertEqual(bd.maand_voortgang("2026-11", date(2027, 3, 1)), 100)   # nooit voorbij het eind
        self.assertEqual(bd.maand_voortgang("2026-11", date(2026, 10, 20)), 0)

    def test_geen_klok_in_het_script(self):
        t = bd.TEMPLATE
        self.assertNotIn("run-paneel", t[t.index("<script>"):])   # het script raakt het paneel niet aan
        self.assertNotIn("run-lijn", t[t.index("<script>"):])

    def test_stil_bij_minder_beweging(self):
        t = bd.TEMPLATE
        css = t[t.index("RUNPANEEL (VA-86)"):t.index("einde RUNPANEEL")]
        blok = css[css.index("@media (prefers-reduced-motion: no-preference){"):]
        blok = blok[:blok.index("}\n  }") + 1]
        self.assertIn("animation:run-klop", blok)
        buiten = css.replace(blok, "")
        self.assertNotRegex(buiten, r"animation(-name)?\s*:")   # elders geen beweging


class Dagcontrole(MetMap):
    """Crit. 5: nog niet actief, of elke nacht om <tijd>."""

    def test_uit(self):
        for c in (plan(), plan(actief=True), plan(tijd="03:00"), plan(actief=False, tijd="03:00")):
            self.assertEqual(self.teksten(c)[0]["controle"], "Dagelijkse controle nog niet actief")

    def test_aan(self):
        self.assertEqual(self.teksten(plan(actief=True, tijd="03:00"))[0]["controle"],
                         "Dagelijkse controle: elke nacht om 03:00")


class FoutSchema(MetMap):
    """Crit. 7: een fout schema breekt de build niet; terugval en een waarschuwing die de sleutel noemt."""

    def setUp(self):
        super().setUp()
        self.werklijst("werklijst_nederland_2026-11.csv")

    def terugval(self, c, sleutel):
        t, let = self.teksten(c)
        self.assertEqual((t["volgende"], t["wijze"]), ("begin december 2026", "handmatig"), c)
        self.assertEqual(t["controle"], "Dagelijkse controle nog niet actief", c)
        self.assertTrue(any(sleutel in regel for regel in let), (sleutel, let))

    def test_onbekende_wijze(self):
        self.terugval(plan(wijze="soms"), "planning.maandrun.wijze")

    def test_dag_buiten_1_tot_28(self):
        for dag in (0, 29, 31, -1, "3", True, 2.5):
            self.terugval(plan(dag=dag), "planning.maandrun.dag")
        self.terugval(plan(wijze="automatisch", dag=30), "planning.maandrun.dag")

    def test_automatisch_zonder_dag(self):
        self.terugval(plan(wijze="automatisch"), "planning.maandrun.dag")

    def test_onleesbare_tijd(self):
        # YAML leest 03:00 zonder aanhalingstekens als het getal 180.
        for tijd in (180, "3 uur", "24:00", "03:60", "3:00"):
            self.terugval(plan(actief=True, tijd=tijd), "planning.dagcontrole.tijd")

    def test_geen_planning(self):
        self.terugval({}, "planning ontbreekt")

    def test_de_build_drukt_de_waarschuwing_af(self):
        payload = {"gebied": "Nederland", "planning_waarschuwingen": ["planning.maandrun.wijze: x"], "bron": None,
                   "bron_reden": "", "leads": []}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bd, "bouw_payload", return_value=payload), \
                mock.patch.object(bd, "render", return_value="<!doctype html>"), \
                mock.patch.object(bd, "OUT", Path(d) / "index.html"), mock.patch.object(bd, "BASE", Path(d)), \
                contextlib.redirect_stdout(io.StringIO()) as uit:
            bd.main()
        self.assertIn("LET OP: planning.maandrun.wijze: x", uit.getvalue())


class Werklijstbestand(MetMap):
    """Crit. 2 en 9: zonder bestand zegt het paneel dat; Delft toont zijn eigen maand."""

    def test_zonder_bestand(self):
        t, _ = self.teksten(plan())
        self.assertEqual((t["laatste"], t["volgende"], t["voortgang"]), ("nog geen werklijst", "nog niet bekend", None))
        self.assertNotIn("run-lijn", bd.planning_paneel(t))   # geen lijn zonder maand
        self.assertTrue(all(t[k] for k in ("laatste", "volgende", "wijze", "controle")))   # geen leeg vak

    def test_delft_eigen_maand(self):
        self.werklijst("werklijst_delft_2026-08.csv", "werklijst_nederland_2026-11.csv", "werklijst_delftse_2026-12.csv")
        t, _ = self.teksten(plan(), "delft")
        self.assertEqual((t["laatste"], t["volgende"]), ("augustus 2026", "begin september 2026"))
        self.assertNotIn("november", woorden(t))

    def test_de_echte_map(self):
        # De gecommitte werklijsten in output/: november 2026 voor Nederland, augustus 2026 voor Delft.
        self.assertEqual(bd.werklijst_maand("nederland"), "2026-11")
        self.assertEqual(bd.werklijst_maand("delft"), "2026-08")


class Pagina(MetMap):
    """Crit. 2, 3, 5 en 6 op de gebouwde pagina: het paneel bovenaan en de zin van de kantoormanager."""

    def bouw(self):
        data = self.map / "data"
        data.mkdir(exist_ok=True)
        lijst = [pand(1, "Amsterdam"), pand(2, "Amsterdam")]
        (data / "panden_nederland.json").write_text(json.dumps(
            {"gebied": "Nederland", "totalen": TOTALEN, "werklijst": lijst, "proef": lijst}), encoding="utf-8")
        (data / "panden_nederland.bron.json").write_text(json.dumps(
            [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]), encoding="utf-8")
        c = {**cfg(), **plan()}
        echt = bd.met_planning
        with mock.patch.object(bd, "DATA", data), mock.patch.object(bd, "OUTPUT", self.map), \
                mock.patch.object(bd, "load_config", lambda: c), \
                mock.patch.object(bd, "met_planning", lambda p, cf: echt(p, cf, vandaag=DAG)):
            payload = bd.bouw_payload()
        return payload, bd.render(payload)

    def test_paneel_en_de_kantoormanager(self):
        self.werklijst("werklijst_nederland_2026-11.csv")
        payload, html = self.bouw()
        i = html.index('<div class="run-paneel"')
        paneel = html[i:html.index('<p class="run-noot">', i)] + html[html.index('<p class="run-noot">', i):].split("</p>")[0]
        tekst = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", paneel)).strip()
        self.assertEqual(tekst, "Laatste run november 2026 Volgende run begin december 2026 handmatig "
                                "Dagelijkse controle nog niet actief")
        self.assertLess(html.index('<div class="spills">'), i)   # bovenaan, onder Bron en Peildatum
        self.assertLess(i, html.index('<h1 id="t-kantoor"'))
        self.assertIn('style="width:50%"', paneel)
        self.assertIn('aria-label="50 % van november 2026 voorbij bij het bouwen van deze pagina"', paneel)
        self.assertNotIn("automatisch", paneel)
        zin = payload["kantoor"]["tekst"]["chef"]["zin"]
        self.assertTrue(zin.endswith(" Volgende run: begin december 2026, handmatig. Dagelijkse controle nog niet actief."), zin)
        self.assertIn("Dagelijkse controle nog niet actief.</span>", html)   # ook in de werkbalk
        self.assertNotIn("planning_waarschuwingen", html)

    def test_dezelfde_dag_dezelfde_pagina(self):
        self.werklijst("werklijst_nederland_2026-11.csv")
        self.assertEqual(self.bouw()[1], self.bouw()[1])

    def test_zonder_planning_geen_paneel(self):
        html = bd.render({"gebied": "Delft", "peildatum": "Peildatum onbekend", "peildatum_tip": "",
                          "kpi": [], "cats": [], "facts": [], "leads": [], "bron": None})
        self.assertNotIn('class="run-paneel"', html)
        self.assertNotIn("__PLANNING__", html)


class Kopij(unittest.TestCase):
    def test_nederlands_zonder_live_online_of_snapshot(self):
        for t in bd.PLANNING_TEKST.values():
            self.assertNotRegex(t.lower(), r"snapshot|\blive\b|\bonline\b|\bnext\b|\brun at\b")

    def test_gecommitte_config_is_handmatig_en_niet_actief(self):
        # Crit. 4 en 5: automatisch en actief komen pas met het verhaal dat de run echt inplant (VA-77).
        p = load_config()["planning"]
        self.assertEqual(p["maandrun"]["wijze"], "handmatig")
        self.assertIs(p["dagcontrole"]["actief"], False)
        self.assertEqual(bd.lees_planning(load_config())[1], [])   # geen waarschuwing op de echte config


if __name__ == "__main__":
    unittest.main()
