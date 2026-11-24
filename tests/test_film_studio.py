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


class Video2XIntegrationTests(unittest.TestCase):
    def test_select_modes(self):
        from film_video2x import options
        self.assertEqual(options({}), ("off", 1))
        self.assertEqual(options({
            "video2x_upscale": "realesrgan-plus", "video2x_rife": 2
        }), ("realesrgan-plus", 2))
        self.assertEqual(options({
            "video2x_upscale": "anime4k-v4-a+a", "video2x_rife": "4"
        }), ("anime4k-v4-a+a", 4))
        for invalid in ("5", "0", "-1", "twice"):
            with self.assertRaises(ValueError):
                options({"video2x_rife": invalid})
        with self.assertRaises(ValueError):
            options({"video2x_upscale": "fake-model"})

    def test_realesrgan_and_rife_cli(self):
        from film_video2x import build_steps
        steps = build_steps(
            "video2x.exe", Path("source.mp4"), Path("output"),
            "realesrgan-plus", 2, 2160, 3840,
        )
        self.assertEqual(len(steps), 2)
        upscale = steps[0][1]
        rife = steps[1][1]
        self.assertIn("realesrgan", upscale)
        self.assertEqual(upscale[upscale.index("-s") + 1], "2")
        self.assertEqual(upscale[upscale.index("--realesrgan-model") + 1], "realesrgan-plus")
        self.assertIn("rife", rife)
        self.assertEqual(rife[rife.index("-m") + 1], "2")
        self.assertEqual(rife[rife.index("--rife-model") + 1], "rife-v4.26")
        self.assertEqual(rife[rife.index("--scene-thresh") + 1], "20")
        self.assertEqual(rife[rife.index("-i") + 1], str(steps[0][2]))
        self.assertTrue(all(isinstance(arg, str) for arg in upscale + rife))

    def test_anime4k_and_no_ai(self):
        from film_video2x import build_steps
        self.assertFalse(build_steps(
            "video2x.exe", Path("source.mp4"), Path("output"),
            "off", 1, 1080, 1920,
        ))
        steps = build_steps(
            "video2x.exe", Path("source.mp4"), Path("output"),
            "anime4k-v4-a+a", 1, 1080, 1920,
        )
        self.assertEqual(len(steps), 1)
        cmd = steps[0][1]
        self.assertEqual(cmd[cmd.index("-w") + 1], "1080")
        self.assertEqual(cmd[cmd.index("-h") + 1], "1920")
        self.assertEqual(cmd[cmd.index("--libplacebo-shader") + 1], "anime4k-v4-a+a")


if __name__ == "__main__":
    unittest.main()
