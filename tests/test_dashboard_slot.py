"""
VA-96: met werklijst.vrij_zichtbaar aan toont de werklijst de eerste n panden en staat de rest achter één
slotblok. Een visueel slot (Aymans besluit): de gegevens blijven in de broncode; op het scherm noemt niets
een pand achter het slot. Geen data nodig: de pagina wordt gebouwd op een tijdelijke data-map.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))
sys.path.insert(0, str(HIER))

import build_dashboard as bd  # noqa: E402
from selectie import load_config  # noqa: E402
from test_dashboard_nederland import TOTALEN, cfg, pand  # noqa: E402


def payload_uit(html):
    return json.loads(re.search(r"const PAYLOAD = (\{.*?\});\r?\n", html, re.S).group(1))


def zonder_payload(html):
    """De HTML zonder het script met de gegevens: wat de browser als opmaak toont."""
    i = html.index("const PAYLOAD = ")
    return html[:i] + html[html.index("\n", i):]


class Gebouwd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.map = Path(self._tmp.name)
        self.lijst = [dict(pand(i, "Amsterdam"), hoofdadres=f"Slotstraat {i}, 1011AA Amsterdam") for i in range(1, 9)]
        (self.map / "panden_nederland.json").write_text(json.dumps(
            {"gebied": "Nederland", "totalen": {**TOTALEN, "werklijst": 8}, "werklijst": self.lijst,
             "proef": self.lijst}), encoding="utf-8")
        (self.map / "panden_nederland.bron.json").write_text(json.dumps(
            [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]), encoding="utf-8")
        p = mock.patch.object(bd, "DATA", self.map)
        p.start()
        self.addCleanup(p.stop)

    def bouw(self, slot="weg"):
        c = cfg()
        if slot != "weg":
            c["werklijst"] = {"vrij_zichtbaar": slot}
        with mock.patch.object(bd, "load_config", lambda: c):
            payload = bd.bouw_payload()
        return bd.render(payload), payload

    def test_uit_en_afwezig_zijn_byte_voor_byte_gelijk(self):
        # Crit. 1: geen slot = de pagina van vandaag.
        weg, _ = self.bouw()
        self.assertEqual(self.bouw(None)[0], weg)
        self.assertEqual(self.bouw(False)[0], weg)
        self.assertNotIn('id="slotBlok"', weg)
        self.assertNotIn('"slot":', weg)

    def test_aan_de_eerste_vijf(self):
        html, p = self.bouw(5)
        self.assertEqual(p["slot"]["n"], 5)
        self.assertEqual(p["slot"]["op_slot"], 3)
        # Ayman: de kop noemt geen aantal; alleen de schermlezer hoort het echte aantal.
        self.assertEqual(p["slot"]["tekst"]["titel"], "De rest van je werklijst staat achter het slot")
        self.assertEqual(p["slot"]["tekst"]["sr"], "3 panden staan achter het slot")
        self.assertIn("const LEADS = PAYLOAD.slot ? ALLE_LEADS.slice(0, PAYLOAD.slot.n) : ALLE_LEADS;", bd.TEMPLATE)
        self.assertEqual([l["id"] for l in p["leads"][:5]], [x["bag_pand_id"] for x in self.lijst[:5]])  # standaardvolgorde
        self.assertEqual(len(p["leads"]), 8)   # de gegevens blijven in de bron (Aymans besluit)

    def test_niets_noemt_een_pand_achter_het_slot(self):
        # Crit. 2 en 3: de opmaak en het slotblok noemen geen adres en geen ID van pand 6 tot 8, en het blok heeft
        # niets om op te tabben of te klikken.
        html, p = self.bouw(5)
        opmaak = zonder_payload(html)
        for x in self.lijst[5:]:
            self.assertNotIn(x["bag_pand_id"], opmaak)
            self.assertNotIn(x["hoofdadres"].split(",")[0], opmaak)
        blok = html[html.index("<!-- SLOT (VA-96) -->"):html.index("<!-- einde SLOT -->")]
        self.assertNotRegex(blok, r"<(a|button|input|select|textarea)\b|tabindex|href=|onclick")
        self.assertIn('aria-hidden="true"', blok)   # de lege kaarten zijn vorm, geen inhoud
        self.assertEqual(len(re.findall(r"<p\b", blok)), 1)   # één tekst voor een schermlezer
        self.assertIn('<b><span aria-hidden="true">De rest van je werklijst staat achter het slot.</span>'
                      '<span class="vh">3 panden staan achter het slot.</span></b> '
                      "Zet de datakoppeling aan om alle panden van de werklijst te zien.", blok)
        zichtbaar = re.sub(r'<span class="vh">[^<]*</span>', "", blok)
        self.assertNotRegex(re.sub(r"<[^>]+>", "", zichtbaar), r"\d")   # geen aantal in beeld

    def test_alleen_de_vrije_panden_worden_kaarten(self):
        # De kaarten, Bewaar/Verberg en 'Open pand' komen alleen uit LEADS; een oud adres #<id> opent niets.
        t = bd.TEMPLATE
        self.assertIn("let rij = LEADS, getoond = 0;", t)
        self.assertIn("const PER_ID = new Map(LEADS.map(d => [d.id, d]));", t)
        # ALLE_LEADS komt alleen voor op de twee regels die LEADS maken; niets anders leest de panden achter het slot.
        regels = [r.strip() for r in t.splitlines() if "ALLE_LEADS" in r]
        self.assertEqual(regels, ["const {kpi:KPI, cats:CATS, facts:FACTS, leads:ALLE_LEADS, budget:BUDGET} = PAYLOAD;",
                                  "const LEADS = PAYLOAD.slot ? ALLE_LEADS.slice(0, PAYLOAD.slot.n) : ALLE_LEADS;",
                                  # Ayman 11-17: een pand dat al bewaard is, opent op Bewaarde panden, ook achter het slot.
                                  "const PER = new Map(ALLE_LEADS.map(d => [String(d.id), d]));"])
        self.assertIn("if (DELEN.includes(start)) ga(start, false);", t)   # een adres opent een deel, nooit een pand

    def test_filters_tellen_de_vijf(self):
        # Crit. 4: de telling zegt hoeveel van de 5 er staan, nooit 'van 8' of 'alle 8'.
        _, p = self.bouw(5)
        tekst = p["filter"]["tekst"]
        self.assertEqual(tekst["alle"], "De 5 zichtbare panden")
        self.assertEqual(tekst["telling"], "{n} van de 5 zichtbare panden")
        self.assertNotIn("8", tekst["alle"] + tekst["telling"])
        _, zonder = self.bouw()
        self.assertEqual(zonder["filter"]["tekst"]["alle"], "Alle 8 panden")

    def test_geen_cijfer_verandert(self):
        # Crit. 5: kerncijfers, de band, zijn stippen en de werklijstkop zijn met en zonder slot gelijk.
        _, uit = self.bouw()
        _, aan = self.bouw(5)
        for k in ("kpi", "cats", "facts", "kaart", "koppen", "kantoor"):
            self.assertEqual(aan.get(k), uit.get(k), k)

    def test_meer_vrij_dan_er_zijn_is_geen_slot(self):
        weg, _ = self.bouw()
        self.assertEqual(self.bouw(8)[0], weg)
        self.assertEqual(self.bouw(20)[0], weg)

    def test_onleesbare_waarde(self):
        for fout in (0, -1, "5", 2.5, True):
            _, p = self.bouw(fout)
            self.assertNotIn("slot", p)
            self.assertTrue(any("werklijst.vrij_zichtbaar" in r for r in p.get("planning_waarschuwingen", [])), fout)


class Vastgelegd(unittest.TestCase):
    def test_gecommitte_config_heeft_het_slot_op_vijf(self):
        self.assertEqual(load_config()["werklijst"]["vrij_zichtbaar"], 5)

    def test_readme_zegt_hoe_het_slot_opengaat_en_wat_het_niet_doet(self):
        readme = (HIER.parent / "README.md").read_text(encoding="utf-8")
        deel = readme[readme.index("## Slot op de werklijst (VA-96)"):]
        for zin in ("vrij_zichtbaar", "null", "build_dashboard.py", "push", "broncode"):
            self.assertIn(zin, deel)

    def test_kopij_nederlands(self):
        for t in bd.SLOT_TEKST.values():
            self.assertNotRegex(t.lower(), r"snapshot|\block\b|\bunlock\b|\blive\b|\bonline\b|\bpay")
        self.assertIn("datakoppeling", bd.SLOT_TEKST["regel"])


if __name__ == "__main__":
    unittest.main()
