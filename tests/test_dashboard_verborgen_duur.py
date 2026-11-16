"""
VA-97: een verborgen pand blijft 30 dagen verborgen (werklijst.verberg_dagen) en staat daarna weer op de
werklijst. Wat VA-90 al verborg, gaat niet verloren. De duur staat in config.yaml en in PAYLOAD.bewaar; het
rekenwerk zit in het script van VA-90. Dat script wordt hier ook echt gedraaid, in Node, met een nagemaakte
localStorage en een vaste klok. Zonder Node slaan alleen die tests over; de bronpinnen blijven.
"""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent))
sys.path.insert(0, str(HIER))

import build_dashboard as bd  # noqa: E402
from selectie import load_config  # noqa: E402
from test_dashboard_bewaren import blok, payload_uit  # noqa: E402

NODE = shutil.which("node")
DAG = 86_400_000
NU = 1_794_000_000_000   # een vaste klok (november 2026), in ms


class Duur(unittest.TestCase):
    def test_config_zegt_30_dagen(self):
        self.assertEqual(load_config()["werklijst"]["verberg_dagen"], 30)
        self.assertEqual(bd.lees_verberg_dagen(load_config()), (30, []))

    def test_afwezig_is_30_en_onleesbaar_is_een_waarschuwing(self):
        self.assertEqual(bd.lees_verberg_dagen({}), (30, []))
        self.assertEqual(bd.lees_verberg_dagen({"werklijst": None}), (30, []))
        self.assertEqual(bd.lees_verberg_dagen({"werklijst": {"verberg_dagen": 14}}), (14, []))
        for fout in (0, -3, "30", 2.5, True):
            n, let = bd.lees_verberg_dagen({"werklijst": {"verberg_dagen": fout}})
            self.assertEqual(n, 30, fout)
            self.assertEqual(len(let), 1, fout)

    def test_payload_draagt_de_duur(self):
        p = bd.met_duur_verborgen({"bewaar": bd.bewaar_blok([])}, {"werklijst": {"verberg_dagen": 7}})
        self.assertEqual(p["bewaar"]["dagen"], 7)
        self.assertEqual(p["bewaar"]["duur"], bd.VERBERG_DUUR_TEKST)
        self.assertEqual(p["bewaar"]["tekst"], bd.BEWAAR_TEKST)
        p = bd.met_duur_verborgen({}, {"werklijst": {"verberg_dagen": "x"}})
        self.assertEqual(p["bewaar"]["dagen"], 30)
        self.assertEqual(len(p["planning_waarschuwingen"]), 1)

    def test_pagina_zonder_config_krijgt_30(self):
        html = bd.render({"gebied": "Delft", "peildatum": "Peildatum onbekend", "peildatum_tip": "",
                          "kpi": [], "cats": [], "facts": [], "leads": [], "bron": None})
        self.assertEqual(payload_uit(html)["bewaar"]["dagen"], 30)


class Script(unittest.TestCase):
    def test_lezen_ruimt_op_en_tonen_ruimt_op(self):
        js = blok()
        self.assertIn("const D = PAYLOAD.bewaar.duur, DAG = 864e5, DAGEN = PAYLOAD.bewaar.dagen || 30;", js)
        self.assertIn("return verlopen();", js)   # elke keer dat de opslag gelezen wordt
        self.assertIn('document.addEventListener("visibilitychange", () => { if (!document.hidden && werkt && verlopen()) overal(true); });', js)
        self.assertIn("else if (tot(r) <= nu) { delete stand[id]; anders = true; } }", js)
        self.assertIn('if (r.stand !== "verborgen") continue;', js.replace("!r || ", ""))   # bewaard verloopt nooit
        self.assertIn('SLEUTEL = "levrai-vastgoed-panden", VORM = 1', js)   # dezelfde sleutel en vorm als VA-90

    def test_kopij_uit_python_en_nederlands(self):
        js = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", blok(), flags=re.S))
        for t in bd.VERBERG_DUUR_TEKST.values():
            self.assertIn("{datum}", t)
            self.assertNotIn(t, js)
            self.assertNotRegex(t.lower(), r"snapshot|\bhide\b|\bshow\b|\buntil\b|\bdays\b")
        self.assertTrue(bd.VERBERG_DUUR_TEKST["label.verborgen"].startswith(bd.BEWAAR_TEKST["label.verborgen"]))


@unittest.skipUnless(NODE, "node staat niet op het pad; het script van VA-90/VA-97 wordt niet gedraaid")
class Gedraaid(unittest.TestCase):
    """Het script van VA-90 in Node: wat staat er na het laden in de opslag, en wat is verborgen."""

    def draai(self, panden, dagen=30, nu=NU, leads=("1", "2", "3", "4")):
        payload = {"bewaar": {"tekst": bd.BEWAAR_TEKST, "dp": "2026-11-01", "dagen": dagen,
                              "duur": bd.VERBERG_DUUR_TEKST}}
        opslag = {"levrai-vastgoed-panden": json.dumps({"v": 1, "panden": panden})}
        prog = """
const vm = require("vm"), fs = require("fs");
const inv = JSON.parse(fs.readFileSync(0, "utf8"));
const winkel = Object.assign({}, inv.opslag);
const ctx = {
  PAYLOAD: inv.payload, LEADS: inv.leads.map(id => ({id, a: "Straat " + id, wp: "Delft", s100: 50, cat: ["A"]})),
  BAG: "https://bag/", nl: n => String(n), maak: () => ({}), JSON, Map, Object, Number, Math, String,
  Date: class extends Date { constructor(...a) { if (a.length) super(...a); else super(inv.nu); }
                             static now() { return inv.nu; } static parse(s) { return Date.parse(s); } },
  localStorage: { getItem: k => (k in winkel ? winkel[k] : null), setItem: (k, v) => { winkel[k] = String(v); },
                  removeItem: k => { delete winkel[k]; } },
  document: { getElementById: () => null, addEventListener: () => {}, hidden: false },
  addEventListener: () => {},
};
vm.createContext(ctx);
vm.runInContext(inv.js + "\\n;this.BW = BW;", ctx);
const uit = {opslag: JSON.parse(winkel["levrai-vastgoed-panden"]), van: {}};
for (const id of inv.leads) uit.van[id] = ctx.BW.van(id);
process.stdout.write(JSON.stringify(uit));
"""
        js = blok()
        js = js[js.index("const BW = "):]
        r = subprocess.run([NODE, "-e", prog], input=json.dumps({"payload": payload, "opslag": opslag, "nu": nu,
                                                                  "js": js, "leads": list(leads)}),
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @staticmethod
    def iso(ms):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def rec(self, stand, sinds):
        return {"stand": stand, "hoofdadres": "Straat", "woonplaats": "Delft", "score100": 50, "pandcategorie": "A",
                "bag_viewer_url": "https://bag/1", "datapeildatum": "2026-11-01", "sinds": sinds}

    def test_binnen_30_dagen_blijft_verborgen(self):
        uit = self.draai({"1": self.rec("verborgen", self.iso(NU - 29 * DAG)),
                          "2": self.rec("verborgen", self.iso(NU - 30 * DAG + 60_000))})
        self.assertEqual((uit["van"]["1"], uit["van"]["2"]), ("verborgen", "verborgen"))
        self.assertEqual(set(uit["opslag"]["panden"]), {"1", "2"})

    def test_na_30_dagen_weer_op_de_werklijst(self):
        uit = self.draai({"1": self.rec("verborgen", self.iso(NU - 30 * DAG)),
                          "2": self.rec("verborgen", self.iso(NU - 400 * DAG)),
                          "3": self.rec("verborgen", self.iso(NU - DAG))})
        self.assertEqual(uit["van"], {"1": "", "2": "", "3": "verborgen", "4": ""})
        self.assertEqual(set(uit["opslag"]["panden"]), {"3"})   # ook uit de opslag, niet alleen uit beeld
        self.assertEqual(uit["opslag"]["v"], 1)

    def test_bewaard_verloopt_nooit(self):
        uit = self.draai({"1": self.rec("bewaard", self.iso(NU - 400 * DAG))})
        self.assertEqual(uit["van"]["1"], "bewaard")
        self.assertEqual(uit["opslag"]["panden"]["1"]["sinds"], self.iso(NU - 400 * DAG))

    def test_oude_vermeldingen_van_va90_blijven(self):
        # Zonder geldige 'sinds' of met een datum in de toekomst: verborgen, en de 30 dagen tellen vanaf nu.
        zonder = self.rec("verborgen", None)
        del zonder["sinds"]
        uit = self.draai({"1": zonder, "2": self.rec("verborgen", "onzin"),
                          "3": self.rec("verborgen", self.iso(NU + 90 * DAG))})
        self.assertEqual([uit["van"][i] for i in "123"], ["verborgen"] * 3)
        for i in "123":
            p = uit["opslag"]["panden"][i]
            self.assertEqual(p["sinds"], self.iso(NU), i)
            self.assertEqual((p["hoofdadres"], p["bag_viewer_url"]), ("Straat", "https://bag/1"))   # de rest blijft

    def test_duur_uit_de_payload(self):
        uit = self.draai({"1": self.rec("verborgen", self.iso(NU - 8 * DAG))}, dagen=7)
        self.assertEqual(uit["van"]["1"], "")
        uit = self.draai({"1": self.rec("verborgen", self.iso(NU - 8 * DAG))}, dagen=30)
        self.assertEqual(uit["van"]["1"], "verborgen")

    def test_pand_buiten_de_lijst_verloopt_ook(self):
        uit = self.draai({"99": self.rec("verborgen", self.iso(NU - 31 * DAG)),
                          "98": self.rec("bewaard", self.iso(NU - 31 * DAG))})
        self.assertEqual(set(uit["opslag"]["panden"]), {"98"})


if __name__ == "__main__":
    unittest.main()
