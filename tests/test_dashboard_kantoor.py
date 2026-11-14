"""
VA-31: het blok PAYLOAD.kantoor dat het pixelkantoor bovenaan het dashboard voedt.
build_dashboard.kantoor() geeft ruwe getallen en ISO-datums; onbekend is None, nooit een
verzonnen of vast getal. bouw_payload() overleeft een ontbrekend panden-bestand en nul
leads. Geen data nodig, behalve de ene test die de echte Delft-cijfers controleert (die
wordt overgeslagen zonder data/panden_delft.json).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_dashboard as bd  # noqa: E402
import selectie  # noqa: E402

DELFT_PANDEN = bd.DATA / "panden_delft.json"


def cfg(energielabel=False, werklijst_min=200, werklijst_max=500, drempel=8):
    """Het deel van config.yaml dat het kantoor leest."""
    return {
        "doelgebied": {"steden": ["Delft"], "provincies": []},
        "drempels": {"score_min_voor_werklijst": drempel,
                     "werklijst_min": werklijst_min, "werklijst_max": werklijst_max},
        "score": {"schaal_max": 26},
        "bronnen": {"energielabel": {"actief": energielabel, "api_key": ""}},
    }


def pand(i, leadscore=8, uitgesloten=False, categorieen=("C",), vbo=3, **extra):
    """Een pand met de velden die bouw_payload() leest."""
    p = {"bag_pand_id": f"0503100000{i:06d}", "uitgesloten": uitgesloten,
         "categorieen": list(categorieen), "leadscore": leadscore,
         "score100": round(leadscore / 26 * 100), "aantal_vbo": vbo,
         "aantal_per_functie": {"woon": vbo}, "bouwjaar": 1900 + i,
         "totale_oppervlakte": 200.0 + i, "opp_per_functie": {"woon": 200.0 + i},
         "score_opbouw": [], "hoofdadres": f"Straat {i}, Delft", "postcode": "2611AA",
         "aantal_adressen": vbo, "woonplaats": "Delft"}
    p.update(extra)
    return p


def snap(woonplaats, datum):
    return {"woonplaats": woonplaats, "bestand": f"vbo_{woonplaats.lower()}.json",
            "ophaaldatum": datum}


class Kantoor(unittest.TestCase):
    def setUp(self):
        self.panden = [pand(1, 12), pand(2, 8), pand(3, 5),
                       pand(4, 9, uitgesloten=True), pand(5, 10, categorieen=())]

    def test_delft_augustus(self):
        bron = [snap("Delft", "2026-08-04")]
        k = bd.kantoor("Delft", bron, self.panden, 2, cfg())
        self.assertEqual(k["gebied"], "Delft")
        # Ingest krijgt de snapshotlijst zelf: het script maakt er '4 aug 2026' van.
        self.assertEqual(k["ingest"], {"bron": bron, "vbo": 15, "verouderd": False})
        self.assertEqual(k["selectie"], {"panden": 5, "a_e": 3, "werklijst": 2, "drempel": 8,
                                         "werklijst_min": 200, "werklijst_max": 500,
                                         "categorieen": {"A": 0, "B": 0, "C": 3, "D": 0, "E": 0}})
        self.assertEqual(k["verrijking"], {"panden": 3, "actief": [], "verrijkt": None})
        self.assertEqual(k["controle"], {"totaal": 2, "te_controleren": 2, "gecontroleerd": None})

    def test_bron_ontbreekt(self):
        k = bd.kantoor("Delft", None, self.panden, 2, cfg())
        # 'Bron onbekend' is de toestand van het script; de payload zegt alleen null,
        # en zet er nooit de rundatum of een vaste datum voor in de plaats.
        self.assertIsNone(k["ingest"]["bron"])
        self.assertEqual(k["ingest"]["vbo"], 15)

    def test_meerdere_woonplaatsen_verschillende_datums(self):
        bron = [snap("Delft", "2026-08-04"), snap("Den Haag", "2026-11-06"),
                snap("Rijswijk", "2026-09-15")]
        k = bd.kantoor("Haaglanden", bron, self.panden, 2, cfg())
        # Alle datums gaan mee; het script toont het bereik, zoals de peildatum-pil (VA-12).
        self.assertEqual([b["ophaaldatum"] for b in k["ingest"]["bron"]],
                         ["2026-08-04", "2026-11-06", "2026-09-15"])
        N = bd.NBSP
        self.assertEqual(bd.peildatum(k["ingest"]["bron"]), f"Peildatum 4{N}aug – 6{N}nov{N}2026")

    def test_energielabel_uit(self):
        k = bd.kantoor("Delft", None, self.panden, 2, cfg(energielabel=False))
        self.assertEqual(k["verrijking"]["actief"], [])
        self.assertIsNone(k["verrijking"]["verrijkt"])

    def test_energielabel_aan_nog_niet_verrijkt(self):
        k = bd.kantoor("Delft", None, self.panden, 2, cfg(energielabel=True))
        self.assertEqual(k["verrijking"]["actief"], ["Energielabel"])
        self.assertEqual(k["verrijking"]["verrijkt"], 0)

    def test_energielabel_aan_en_verrijkt(self):
        panden = self.panden + [pand(6, 9, energielabel_status="gevonden", energielabel="F"),
                                pand(7, 4, energielabel_status="geen"),
                                pand(8, 9, uitgesloten=True, energielabel_status="gevonden")]
        k = bd.kantoor("Delft", None, panden, 2, cfg(energielabel=True))
        # Alleen panden binnen A–E tellen; het uitgesloten pand niet.
        self.assertEqual(k["verrijking"]["verrijkt"], 2)
        self.assertEqual(k["verrijking"]["panden"], 5)

    def test_actief_alleen_bij_true(self):
        c = cfg()
        c["bronnen"]["energielabel"]["actief"] = "false"
        self.assertEqual(bd.actieve_bronnen(c), [])
        self.assertEqual(bd.actieve_bronnen({}), [])

    def test_nul_leads(self):
        k = bd.kantoor("Delft", None, [pand(1, 9, uitgesloten=True)], 0, cfg())
        self.assertEqual(k["controle"], {"totaal": 0, "te_controleren": 0, "gecontroleerd": None})
        self.assertEqual(k["selectie"]["a_e"], 0)
        self.assertEqual(k["selectie"]["werklijst"], 0)

    def test_controle_volgt_het_aantal_leads(self):
        # Geen vaste 20: het getal is wat de payload aan leads heeft.
        self.assertEqual(bd.kantoor("Delft", None, self.panden, 7, cfg())["controle"]["totaal"], 7)

    def test_geen_data(self):
        k = bd.kantoor("Delft", None, None, None, cfg())
        self.assertEqual(k["ingest"], {"bron": None, "vbo": None, "verouderd": False})
        self.assertEqual(k["selectie"], {"panden": None, "a_e": None, "werklijst": None,
                                         "drempel": 8, "werklijst_min": 200, "werklijst_max": 500,
                                         "categorieen": None})
        self.assertEqual(k["verrijking"], {"panden": None, "actief": [], "verrijkt": None})
        self.assertEqual(k["controle"], {"totaal": None, "te_controleren": None,
                                         "gecontroleerd": None})

    def test_drempels_uit_config(self):
        k = bd.kantoor("Delft", None, self.panden, 2,
                       cfg(werklijst_min=300, werklijst_max=700, drempel=10))
        self.assertEqual(k["selectie"]["drempel"], 10)
        self.assertEqual(k["selectie"]["werklijst"], 1)
        self.assertEqual((k["selectie"]["werklijst_min"], k["selectie"]["werklijst_max"]), (300, 700))

    def test_ontbrekende_drempels_worden_null(self):
        c = cfg()
        del c["drempels"]
        k = bd.kantoor("Delft", None, self.panden, 2, c)
        self.assertIsNone(k["selectie"]["drempel"])
        self.assertIsNone(k["selectie"]["werklijst"])
        self.assertIsNone(k["selectie"]["werklijst_min"])


class BouwPayload(unittest.TestCase):
    """bouw_payload() op een tijdelijke data-map: overleeft geen data en nul leads."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.map = Path(self._tmp.name)
        self._p = [mock.patch.object(bd, "DATA", self.map),
                   mock.patch.object(bd, "load_config", lambda: cfg())]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        self._tmp.cleanup()

    def _schrijf(self, panden, bron=None):
        pad = self.map / "panden_delft.json"
        pad.write_text(json.dumps(panden), encoding="utf-8")
        if bron is not None:
            b = self.map / "panden_delft.bron.json"
            b.write_text(json.dumps(bron), encoding="utf-8")
            later = pad.stat().st_mtime + 1
            os.utime(b, (later, later))

    def test_geen_panden_bestand(self):
        payload = bd.bouw_payload()
        k = payload["kantoor"]
        self.assertIsNone(k["ingest"]["vbo"])
        self.assertIsNone(k["selectie"]["panden"])
        self.assertIsNone(k["controle"]["totaal"])
        self.assertEqual(payload["leads"], [])
        self.assertIsNone(payload["bron"])
        self.assertIn("panden_delft.json ontbreekt", payload["bron_reden"])
        # Geen verzonnen nullen in de KPI's: onbekend is onbekend.
        self.assertEqual([x["v"] for x in payload["kpi"]], ["onbekend"] * 4)
        self.assertIn("onbekend", [f["val"] for f in payload["facts"]])
        html = bd.render(payload)
        self.assertIn('"kantoor":', html)

    def test_onleesbaar_panden_bestand(self):
        (self.map / "panden_delft.json").write_text("{kapot", encoding="utf-8")
        payload = bd.bouw_payload()
        self.assertIsNone(payload["kantoor"]["selectie"]["panden"])
        self.assertIn("niet leesbaar", payload["bron_reden"])

    def test_nul_leads(self):
        self._schrijf([pand(1, 9, uitgesloten=True), pand(2, 9, categorieen=())])
        payload = bd.bouw_payload()
        self.assertEqual(payload["leads"], [])
        self.assertEqual(payload["kantoor"]["controle"]["totaal"], 0)
        self.assertEqual(payload["kantoor"]["selectie"]["panden"], 2)
        feiten = {f["k"]: f["val"] for f in payload["facts"]}
        self.assertEqual(feiten["Panden in proefselectie"], "0")
        self.assertEqual(feiten["Score-index (/100)"], "onbekend")
        self.assertEqual(feiten["Gem. oppervlakte"], "onbekend")
        bd.render(payload)

    def test_kantoor_en_kpi_tonen_dezelfde_werklijst(self):
        self._schrijf([pand(i, 6 + i % 5) for i in range(30)],
                      bron=[snap("Delft", "2026-08-04")])
        payload = bd.bouw_payload()
        kpi = int(payload["kpi"][3]["v"].replace(".", ""))
        self.assertEqual(payload["kantoor"]["selectie"]["werklijst"], kpi)
        self.assertEqual(payload["kantoor"]["controle"]["totaal"], len(payload["leads"]))
        self.assertEqual(payload["kantoor"]["ingest"]["bron"], payload["bron"])


class Landelijk(unittest.TestCase):
    """Criterium 5: een handgeschreven landelijk blok gaat ongewijzigd en ongeformatteerd door."""

    def test_nederland(self):
        bron = [snap(f"Plaats{i:04d}", f"2026-{10 + i % 2:02d}-{1 + i % 28:02d}") for i in range(2500)]
        k = {"gebied": "Nederland",
             "ingest": {"bron": bron, "vbo": 9978773, "verouderd": False},
             "selectie": {"panden": 3912408, "a_e": 387215, "werklijst": 1234567, "drempel": 8,
                          "werklijst_min": 200, "werklijst_max": 500},
             "verrijking": {"panden": 387215, "actief": [], "verrijkt": None},
             "controle": {"totaal": 20, "te_controleren": 20, "gecontroleerd": None}}
        payload = {"gebied": "Nederland", "bron": bron, "peildatum": bd.peildatum(bron),
                   "peildatum_tip": "", "kantoor": k}
        html = bd.render(payload)
        # Ruwe getallen: de punten zet het script, met dezelfde regel als de KPI's.
        self.assertIn('"werklijst": 1234567', html)
        # De bron staat twee keer in de pagina: PAYLOAD.bron en PAYLOAD.kantoor.ingest.bron.
        self.assertEqual(html.count('"ophaaldatum"'), 2 * 2500)


class Pagina(unittest.TestCase):
    """Het kantoor staat bovenaan, haakt in op PAYLOAD.kantoor en laadt niets van buiten."""

    def test_plaats_en_aanhaakpunt(self):
        # Sinds VA-64 staat het kantoor (#pk) in het eerste deel van de pagina, #kantoor,
        # vóór de kerncijfers; de kop van dat deel staat erboven.
        t = bd.TEMPLATE
        kantoor = t.index('<section class="deel" id="kantoor"')
        self.assertLess(t.index('<main class="inhoud"'), kantoor)
        self.assertLess(kantoor, t.index('<div class="pk" id="pk"'))
        self.assertLess(t.index('<div class="pk" id="pk"'), t.index('<div class="kpis" id="kpis"'))
        self.assertLess(t.index('<header class="kop">', kantoor), t.index('<div class="pk" id="pk"'))
        self.assertEqual(t.count('<section class="deel"', t.index('<main'), kantoor), 0)
        self.assertIn("kantoorStart(pk, PAYLOAD.kantoor)", t)  # VA-60, na het laden van three.js
        self.assertIn("<canvas", t)

    def test_kantoor_altijd_zichtbaar(self):
        # Ayman bij de review: geen knop 'verberg kantoor', het kantoor staat er altijd.
        t = bd.TEMPLATE
        for weg in ('id="pkKnop"', "Verberg kantoor", "Toon kantoor", "aria-pressed",
                    ".pk[hidden]", "toon(aan)", "root.hidden = "):
            self.assertNotIn(weg, t)
        for begin in ('<section class="deel" id="kantoor"', '<div class="pk" id="pk"'):
            tag = t[t.index(begin):]
            self.assertNotIn("hidden", tag[:tag.index(">")], begin)

    def test_niets_van_buiten(self):
        t = bd.TEMPLATE.lower()
        for verboden in ("<link", "@import", "url(", "@font-face"):
            self.assertNotIn(verboden, t)
        # VA-60: de enige bron van buiten is three.js r128 van cdnjs, met integrity en crossorigin.
        # De pagina laadt het zelf, zodat een hangende cdnjs de rest niet ophoudt.
        self.assertNotIn("<script src", t)
        self.assertEqual(t.count('s.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";'), 1)
        self.assertIn('s.integrity = "sha512-', t)
        self.assertIn('s.crossorigin = "anonymous"', t)
        self.assertIn("settimeout(start, 4000)", t)  # t is in kleine letters
        self.assertEqual(t.count("https://") - t.count("https://bagviewer.kadaster.nl"), 1)

    def test_script_maakt_geen_zinnen(self):
        # Nova, VA-31 criteria 2 en 4: de zinnen komen uit kantoor_teksten() in Python en
        # staan op één plek. Het script toont PAYLOAD.kantoor.tekst en maakt zelf niets op.
        t = bd.TEMPLATE
        for weg in ("panden op de werklijst", "BAG opgehaald", "Geen extra bron actief",
                    "wachten op visuele controle", "const REGELS", "const TEKST =", "const UITLEG",
                    "Kijk even bij", "die je aandacht vra"):
            self.assertNotIn(weg, t)
        self.assertIn("data.tekst[id]", t)

    def test_een_kantoorscript_zonder_ontwerppagina(self):
        # Alleen het blok tussen BEGIN en het einde van PK, niet de 'Voor Ada'-notities of
        # de voorbeeldcijfers (ECHT) van de ontwerppagina.
        t = bd.TEMPLATE
        self.assertEqual(t.count("BEGIN PIXELKANTOOR"), 1)
        self.assertEqual(t.count("const PK = (() => {"), 1)
        self.assertNotIn("const ECHT", t)
        self.assertNotIn("<li>", t)
        self.assertNotIn("Voor Ada", t)

    def test_escape_sluit_de_uitleg(self):
        self.assertIn('e.key === "Escape"', bd.TEMPLATE)


def hard(tekst):
    """Datums zoals _nl() ze geeft: harde spaties (VA-12)."""
    return tekst.replace(" ", bd.NBSP)


class Teksten(unittest.TestCase):
    """VA-31 criteria 2, 3, 4 en 5: de exacte regel die elke medewerker toont."""

    def setUp(self):
        self.panden = [pand(1, 12), pand(2, 8), pand(3, 5),
                       pand(4, 9, uitgesloten=True), pand(5, 10, categorieen=())]

    def bel(self, k):
        return {wie: (r["s"], r["bel"]) for wie, r in k["tekst"].items() if wie != "chef"}

    def test_delft_augustus(self):
        k = bd.kantoor("Delft", [snap("Delft", "2026-08-04")], self.panden, 20, cfg(werklijst_min=1))
        self.assertEqual(self.bel(k), {
            "ingest": ("werkt", "BAG opgehaald " + hard("4 aug 2026")),
            "selectie": ("werkt", "2 panden op de werklijst"),
            "verrijking": ("slaapt", "Geen extra bron actief"),
            "controle": ("aandacht", "20 panden wachten op visuele controle"),
        })
        self.assertEqual(k["tekst"]["ingest"]["zin"],
                         "Ingest heeft de BAG van Delft opgehaald op " + hard("4 aug 2026") + ": 15 verblijfsobjecten.")

    def test_bron_ontbreekt(self):
        k = bd.kantoor("Delft", None, self.panden, 2, cfg())
        self.assertEqual(self.bel(k)["ingest"], ("aandacht", "Bron onbekend"))
        self.assertNotIn("opgehaald op", k["tekst"]["ingest"]["zin"])

    def test_onleesbare_datum(self):
        k = bd.kantoor("Delft", [snap("Delft", "gisteren")], self.panden, 2, cfg())
        self.assertEqual(self.bel(k)["ingest"], ("aandacht", "Ophaaldatum onbekend"))

    def test_meerdere_woonplaatsen_verschillende_datums(self):
        bron = [snap("Delft", "2026-08-04"), snap("Den Haag", "2026-11-06"),
                snap("Rijswijk", "2026-09-15")]
        k = bd.kantoor("Haaglanden", bron, self.panden, 2, cfg())
        bel = k["tekst"]["ingest"]["bel"]
        self.assertEqual(bel, f"BAG opgehaald 4{bd.NBSP}aug{bd.NBSP}–{bd.WJ}{bd.NBSP}6{bd.NBSP}nov{bd.NBSP}2026")
        self.assertIn("tussen " + hard("4 aug") + " en " + hard("6 nov 2026"), k["tekst"]["ingest"]["zin"])

    def test_bereik_over_een_jaargrens(self):
        k = bd.kantoor("NL", [snap("A", "2025-12-30"), snap("B", "2026-01-02")], self.panden, 2, cfg())
        self.assertIn(hard("30 dec 2025"), k["tekst"]["ingest"]["bel"])

    def test_energielabel_uit_en_aan(self):
        uit = bd.kantoor("Delft", None, self.panden, 2, cfg(energielabel=False))
        self.assertEqual(self.bel(uit)["verrijking"], ("slaapt", "Geen extra bron actief"))
        aan = bd.kantoor("Delft", None, self.panden, 2, cfg(energielabel=True))
        self.assertEqual(self.bel(aan)["verrijking"], ("aandacht", "Energielabel nog niet opgehaald"))
        verrijkt = [pand(1, 12, energielabel_status="ontbreekt"), pand(2, 8, energielabel_status="G"), pand(3, 5)]
        k = bd.kantoor("Delft", None, verrijkt, 2, cfg(energielabel=True))
        self.assertEqual(self.bel(k)["verrijking"], ("werkt", "Energielabel bij 2 panden"))

    def test_nul_leads(self):
        k = bd.kantoor("Delft", None, self.panden, 0, cfg())
        self.assertEqual(self.bel(k)["controle"], ("leeg", "Geen panden om te controleren"))

    def test_werklijst_onder_de_gebruikelijke(self):
        k = bd.kantoor("Delft", None, self.panden, 2, cfg())
        self.assertEqual(self.bel(k)["selectie"], ("aandacht", "2 op de werklijst: onder de gebruikelijke 200–500"))
        self.assertIn("De werklijst wordt wel gemaakt", k["tekst"]["selectie"]["zin"])
        self.assertNotIn("ondergrens", json.dumps(k["tekst"], ensure_ascii=False))

    def test_geen_data(self):
        k = bd.kantoor("Delft", None, None, None, cfg())
        self.assertEqual({w: s for w, (s, _) in self.bel(k).items()},
                         {"ingest": "leeg", "selectie": "leeg", "verrijking": "leeg", "controle": "leeg"})
        self.assertEqual(k["tekst"]["ingest"]["bel"], "Nog geen BAG opgehaald")

    def test_onbekend_getal_is_onbekend(self):
        self.assertEqual(bd.nl_getal(None), "onbekend")
        self.assertEqual(bd.nl_getal(1234567), "1.234.567")
        self.assertEqual(bd.nl_getal(0), "0")

    def test_nederland(self):
        bron = [snap(f"Plaats{i:04d}", f"2026-{10 + i % 2:02d}-{1 + i % 28:02d}") for i in range(2500)]
        k = {"gebied": "Nederland",
             "ingest": {"bron": bron, "vbo": 9999826, "verouderd": False},
             "selectie": {"panden": 3912408, "a_e": 387215, "werklijst": 1234567, "drempel": 8,
                          "werklijst_min": 200, "werklijst_max": 500},
             "verrijking": {"panden": 387215, "actief": [], "verrijkt": None},
             "controle": {"totaal": 500, "te_controleren": 500, "gecontroleerd": None}}
        t = bd.kantoor_teksten(k)
        # Eén datumregel voor 2.500 woonplaatsen, en getallen met duizendtallenpunten.
        self.assertEqual(t["ingest"]["bel"], f"BAG opgehaald 1{bd.NBSP}okt{bd.NBSP}–{bd.WJ}{bd.NBSP}28{bd.NBSP}nov{bd.NBSP}2026")
        self.assertIn("9.999.826 verblijfsobjecten", t["ingest"]["zin"])
        self.assertEqual(t["selectie"]["bel"], "1.234.567 panden op de werklijst")
        self.assertEqual(t["controle"]["bel"], "500 panden wachten op visuele controle")
        self.assertIn("Nederland", t["selectie"]["uitleg"])


class Kantoormanager(unittest.TestCase):
    """VA-60 criterium 3: wat de kantoormanager zegt, exact (copy van VA-48)."""

    def chef(self, **toestanden):
        alle = {"ingest": "werkt", "selectie": "werkt", "verrijking": "slaapt", "controle": "werkt"}
        alle.update(toestanden)
        return bd.chef_teksten(alle)

    def test_niemand(self):
        self.assertEqual(self.chef()["zin"],
                         "Niemand vraagt nu je aandacht. De kantoormanager loopt een ronde door het kantoor.")

    def test_een(self):
        self.assertEqual(self.chef(controle="aandacht")["zin"], "Loopt naar Controle, die je aandacht vraagt.")

    def test_twee_en_drie(self):
        self.assertEqual(self.chef(ingest="aandacht", controle="aandacht")["zin"],
                         "Loopt langs Ingest en Controle, die je aandacht vragen.")
        self.assertEqual(self.chef(ingest="aandacht", selectie="aandacht", controle="aandacht")["zin"],
                         "Loopt langs Ingest, Selectie en Controle, die je aandacht vragen.")

    def test_ballon_per_medewerker(self):
        self.assertEqual(self.chef()["bel"], {"ingest": "Kijk even bij Ingest", "selectie": "Kijk even bij Selectie",
                                              "verrijking": "Kijk even bij Verrijking",
                                              "controle": "Kijk even bij Controle"})

    def test_in_het_tekstblok(self):
        k = bd.kantoor("Delft", [snap("Delft", "2026-08-04")], [pand(1, 12)], 20, cfg(werklijst_min=1))
        self.assertEqual(k["tekst"]["chef"]["zin"], "Loopt naar Controle, die je aandacht vraagt.")


class Pagina3D(unittest.TestCase):
    """VA-60: de 3D-laag staat in de pagina, zonder de hulpmiddelen van de ontwerppagina."""

    def test_3d_blok_en_terugval(self):
        t = bd.TEMPLATE
        self.assertEqual(t.count("const bouwPK3D = () => (() => {"), 1)  # pas na het laden gebouwd
        self.assertEqual(t.count("function kantoorStart("), 1)
        self.assertIn("PK.start(root, data, opties)", t)  # terugval op het 2D-kantoor van VA-31
        self.assertIn("PK.lees(data, id)", t)

    def test_geen_ontwerphulpmiddelen(self):
        t = bd.TEMPLATE
        for weg in ("stilKnop", "Stilstaand beeld", 'id="vel"', "const ECHT", "copyTabel", "<li>"):
            self.assertNotIn(weg, t)


def delft_config():
    """De gecommitte config.yaml, maar met Delft gekozen (VA-39: de gecommitte kiest Nederland)."""
    c = selectie.load_config()
    c["doelgebied"]["nederland"] = False
    return c


@unittest.skipUnless(DELFT_PANDEN.is_file(), f"{DELFT_PANDEN} ontbreekt; echte Delft-cijfers overgeslagen")
class EchteDelftCijfers(unittest.TestCase):
    def test_kantoor_uit_de_echte_payload(self):
        # VA-39 crit. 8: de Delftse bouw werkt nog als Delft gekozen is.
        with mock.patch.object(bd, "load_config", delft_config):
            payload = bd.bouw_payload()
        k = payload["kantoor"]
        self.assertEqual(k["gebied"], "Delft")
        self.assertEqual(k["ingest"]["vbo"], 61993)
        self.assertEqual(k["selectie"]["panden"], 24008)
        self.assertEqual(k["selectie"]["a_e"], 2346)
        self.assertEqual(k["selectie"]["werklijst"], 1668)
        self.assertEqual(k["selectie"]["werklijst"], int(payload["kpi"][3]["v"].replace(".", "")))
        self.assertEqual(k["controle"]["totaal"], len(payload["leads"]))
        self.assertEqual(k["ingest"]["bron"], payload["bron"])
        # De regels zoals Levrai ze op de pagina leest.
        self.assertEqual(k["tekst"]["selectie"]["bel"], "1.668 panden op de werklijst")
        self.assertEqual(k["tekst"]["verrijking"]["bel"], "Geen extra bron actief")
        self.assertEqual(k["tekst"]["controle"]["bel"],
                         f"{len(payload['leads'])} panden wachten op visuele controle")


NL_PANDEN = bd.DATA / "panden_nederland.json"


@unittest.skipUnless(NL_PANDEN.is_file(), f"{NL_PANDEN} ontbreekt; echte landelijke cijfers overgeslagen")
class EchteNederlandCijfers(unittest.TestCase):
    """VA-39 crit. 2 en 6: de figuren van de pagina en het kantoor zijn de totalen van VA-37."""

    @classmethod
    def setUpClass(cls):
        cls.t = json.loads(NL_PANDEN.read_text(encoding="utf-8"))["totalen"]
        cfg = selectie.load_config()
        cfg["doelgebied"]["nederland"] = True
        with mock.patch.object(bd, "load_config", lambda: cfg):
            cls.payload = bd.bouw_payload()

    def test_kerncijfers_zijn_de_totalen(self):
        t, kpi = self.t, self.payload["kpi"]
        self.assertEqual([int(k["v"].replace(".", "")) for k in kpi],
                         [t["vbo"], t["panden"], t["a_e"], t["geschikt"]])
        self.assertEqual(kpi[1]["h"], f"{bd.nl_getal(t['uitgesloten'])} uitgesloten")
        self.assertEqual(kpi[3]["l"], f"Geschikt · score ≥ {t['drempel']}")
        self.assertEqual(kpi[3]["h"], f"{bd.nl_getal(t['geschikt_25'])} in de {t['aantal_grote_gemeenten']} "
                                      f"grootste gemeenten · {bd.nl_getal(t['geschikt_overig'])} elders")
        self.assertNotIn("dekking", kpi[0]["h"])  # Lumi: geen dekkingspercentage tegen de WFS
        self.assertEqual({c["k"]: c["n"] for c in self.payload["cats"]}, t["categorieen"])
        feiten = {f["k"]: f["val"] for f in self.payload["facts"]}
        self.assertEqual(feiten["Panden op de werklijst"], bd.nl_getal(t["werklijst"]))
        self.assertEqual(feiten[f"Uit de {t['aantal_grote_gemeenten']} grootste gemeenten"],
                         bd.nl_getal(t["werklijst_25"]))
        self.assertEqual(feiten["Elders in Nederland"], bd.nl_getal(t["werklijst_overig"]))
        self.assertNotIn("Oudste pand", feiten)
        self.assertNotIn("Bron-snapshot", feiten)

    def test_lijst_en_verdeling_kloppen_met_de_totalen(self):
        leads, t = self.payload["leads"], self.t
        self.assertEqual(len(leads), t["werklijst"])
        meta = self.payload["koppen"]["werklijst.meta"]
        self.assertEqual(meta, f"{t['werklijst']} panden · {t['werklijst_25']} uit de "
                               f"{t['aantal_grote_gemeenten']} grootste gemeenten · {t['werklijst_overig']} elders")
        self.assertEqual(sum(o["aantal"] for g in self.payload["filter"]["groepen"] for o in g["opties"]),
                         len(leads))

    def test_kantoor_reageert_op_het_land(self):
        k, t = self.payload["kantoor"], self.t
        self.assertEqual(k["gebied"], "Nederland")
        self.assertEqual((k["ingest"]["vbo"], k["selectie"]["panden"], k["selectie"]["a_e"]),
                         (t["vbo"], t["panden"], t["a_e"]))
        self.assertEqual(k["selectie"]["categorieen"], t["categorieen"])  # het bord in de taxatiekamer
        self.assertEqual(k["tekst"]["selectie"]["bel"], f"{t['werklijst']} panden op de werklijst")
        self.assertIn(f"{bd.nl_getal(t['geschikt'])} halen score {t['drempel']} of hoger; de {t['werklijst']} "
                      "beste staan op de werklijst.", k["tekst"]["selectie"]["zin"])
        self.assertTrue(k["tekst"]["ingest"]["zin"].startswith("Ingest heeft de BAG van heel Nederland ingelezen"))
        self.assertEqual(k["controle"]["totaal"], len(self.payload["leads"]))


class KantoorLandelijk(unittest.TestCase):
    """Lumi's kopij VA-39 voor het kantoor, op handgemaakte totalen van de eerste landelijke run."""

    T = {"vbo": 9998456, "panden": 6568913, "uitgesloten": 475372, "a_e": 441997,
         "categorieen": {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}, "geschikt": 263319, "geschikt_25": 139846,
         "geschikt_overig": 123473, "werklijst": 500, "werklijst_25": 450, "werklijst_overig": 50,
         "drempel": 8, "maand": "2026-11", "aantal_grote_gemeenten": 25}

    def test_lumis_regels(self):
        bron = [{"woonplaats": "Nederland", "bestand": "bag_nl_2026-11-01.sqlite", "ophaaldatum": "2026-11-01"}]
        k = bd.kantoor_landelijk(bron, self.T, 500, cfg())
        tk = k["tekst"]
        self.assertEqual(tk["ingest"]["bel"], "BAG opgehaald " + hard("1 nov 2026"))
        self.assertEqual(tk["ingest"]["zin"], "Ingest heeft de BAG van heel Nederland ingelezen uit het "
                                              f"bestand van {hard('1 nov 2026')}: 9.998.456 verblijfsobjecten.")
        self.assertEqual(tk["ingest"]["uitleg"],
                         "Ingest leest de BAG van heel Nederland in uit het GeoPackage-bestand van PDOK, de open "
                         "dataset van het Kadaster. Elke ophaling blijft bewaard als eigen, gedateerde "
                         "momentopname, zodat je altijd ziet uit welke ophaling een cijfer komt.")
        self.assertEqual(tk["selectie"]["bel"], "500 panden op de werklijst")
        self.assertEqual(tk["selectie"]["zin"], "Selectie heeft 441.997 panden in categorie A–E gescoord. "
                                                "263.319 halen score 8 of hoger; de 500 beste staan op de werklijst.")
        self.assertEqual(tk["selectie"]["uitleg"],
                         "Selectie groepeert de verblijfsobjecten per BAG-pand, sluit panden uit die buiten de "
                         "briefing vallen, deelt de rest in categorie A–E in en geeft elk pand een leadscore. "
                         "Van de 6.568.913 panden in Nederland vallen er 441.997 in A–E; 263.319 halen score 8 "
                         "of hoger. Daaruit komen de 500 hoogst scorende op de werklijst: 450 uit de 25 "
                         "gemeenten met de meeste inwoners (CBS) en 50 elders in Nederland. Bij gelijke score "
                         "beslist een loting die de hele maand gelijk blijft.")
        self.assertEqual(tk["controle"]["bel"], "500 panden wachten op visuele controle")
        self.assertTrue(tk["controle"]["uitleg"].startswith(
            "Controle zet de 500 panden van de werklijst klaar voor je visuele controle."))
        self.assertEqual(tk["verrijking"]["bel"], "Geen extra bron actief")  # ongewijzigd

    def test_zonder_totalen_onbekend(self):
        k = bd.kantoor_landelijk(None, None, None, cfg())
        self.assertEqual({k["tekst"][w]["s"] for w in ("ingest", "selectie", "verrijking", "controle")}, {"leeg"})


if __name__ == "__main__":
    unittest.main()
