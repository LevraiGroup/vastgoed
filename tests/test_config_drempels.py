"""
VA-41: onmogelijke werklijst-drempels in config.yaml stoppen de run, met een Nederlandse
melding die de sleutel en de waarde noemt. VA-43: nl_tal() geeft de duizendtallenpunt.
Alleen standaardbibliotheek; geen data nodig.
"""
import copy
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_proef  # noqa: E402
import selectie  # noqa: E402

GOED = {"score": {"schaal_max": 26},
        "drempels": {"score_min_voor_werklijst": 8, "werklijst_min": 200, "werklijst_max": 500}}


def met(**drempels):
    cfg = copy.deepcopy(GOED)
    cfg["drempels"].update(drempels)
    return cfg


class Drempels(unittest.TestCase):
    def test_huidige_config_is_in_orde(self):
        self.assertEqual(selectie.controleer_drempels(selectie.load_config()), [])
        self.assertEqual(selectie.controleer_drempels(GOED), [])

    def test_elk_onmogelijk_geval(self):
        gevallen = {
            "werklijst_min = '200' is geen heel getal": met(werklijst_min="200"),
            "werklijst_min = 2.5 is geen heel getal": met(werklijst_min=2.5),
            "werklijst_max = None is geen heel getal": met(werklijst_max=None),
            "werklijst_max = True is geen heel getal": met(werklijst_max=True),
            "werklijst_max = 0 is kleiner dan 1": met(werklijst_min=0, werklijst_max=0),
            "werklijst_min = -1 is kleiner dan 0": met(werklijst_min=-1),
            "werklijst_min = 600 is groter dan drempels.werklijst_max = 500": met(werklijst_min=600),
            "score_min_voor_werklijst = 'acht' is geen getal": met(score_min_voor_werklijst="acht"),
            "score_min_voor_werklijst = nan is geen getal": met(score_min_voor_werklijst=float("nan")),
            "score_min_voor_werklijst = 27 is hoger dan score.schaal_max = 26": met(score_min_voor_werklijst=27),
        }
        for verwacht, cfg in gevallen.items():
            with self.subTest(verwacht=verwacht):
                fouten = selectie.controleer_drempels(cfg)
                self.assertEqual(len(fouten), 1, fouten)
                self.assertIn(verwacht, fouten[0])

    def test_grenswaarden_mogen(self):
        self.assertEqual(selectie.controleer_drempels(met(werklijst_min=0, werklijst_max=1)), [])
        self.assertEqual(selectie.controleer_drempels(met(werklijst_min=500, score_min_voor_werklijst=26)), [])

    def test_run_stopt_voor_het_schrijven(self):
        err = io.StringIO()
        with mock.patch.object(run_proef, "load_config", return_value=met(werklijst_max=0)), \
                mock.patch.object(run_proef, "verwerk") as verwerk, \
                mock.patch.object(sys, "argv", ["run_proef.py"]), redirect_stderr(err):
            code = run_proef.main()
        self.assertNotEqual(code, 0)
        verwerk.assert_not_called()
        self.assertIn("FOUT in config.yaml: drempels.werklijst_max = 0", err.getvalue())


class NlTal(unittest.TestCase):
    def test_punt(self):
        self.assertEqual(selectie.nl_tal(61993), "61.993")
        self.assertEqual(selectie.nl_tal(1668), "1.668")
        self.assertEqual(selectie.nl_tal(999), "999")
        self.assertEqual(selectie.nl_tal(9999826), "9.999.826")
        self.assertEqual(selectie.nl_tal(287.4), "287")
        self.assertEqual(selectie._nl(1668), "1.668")  # oude naam blijft werken


if __name__ == "__main__":
    unittest.main()
