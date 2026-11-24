"""Offline tests for Film & Series Studio core validation."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webjs"))

class CatalogValidationTests(unittest.TestCase):
    def test_only_known_https_hosts(self):
        from film_catalog import validate_url
        self.assertEqual(
            validate_url("https://hdrezka.rest/series/test-episode.html"),
            "https://hdrezka.rest/series/test-episode.html",
        )
        with self.assertRaises(ValueError):
            validate_url("http://hdrezka.rest/series/test.html")
        with self.assertRaises(ValueError):
            validate_url("https://hdrezka.rest.evil.example/test.html")
        with self.assertRaises(ValueError):
            validate_url("https://localhost/film.html")
        with self.assertRaises(ValueError):
            validate_url("https://hdrezka.rest/")

    def test_source_times(self):
        from film_render import sec
        self.assertAlmostEqual(sec("01:02:03.5"), 3723.5)
        self.assertAlmostEqual(sec("02:15"), 135)
        self.assertEqual(sec("0"), 0)
        with self.assertRaises(ValueError):
            sec("bad")

    def test_face_curve(self):
        from film_render import _curve
        self.assertEqual(_curve([], 0, 1920, 608), "656")
        result = _curve([(0.0, 900, 420), (1.0, 950, 420)], 0, 1920, 608)
        self.assertIn("if(lt(t,1.000)", result)
        self.assertNotIn("nan", result.lower())

if __name__ == "__main__":
    unittest.main()
