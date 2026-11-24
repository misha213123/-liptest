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


class FilmRuntimeRecoveryTests(unittest.TestCase):
    def test_whisper_cuda_runtime_fallback_at_transcribe(self):
        from unittest.mock import patch
        from film_runtime import transcribe_segments

        calls = []

        class Whisper:
            def __init__(self, device):
                self.device = device
            def transcribe(self, *_args, **_kwargs):
                if self.device == "cuda":
                    raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                return iter(["cpu speech"]), None

        def factory(_name, **kwargs):
            calls.append((kwargs["device"], kwargs["compute_type"]))
            return Whisper(kwargs["device"])

        with patch("film_runtime._cuda_dll_present", return_value=True):
            segments = transcribe_segments("test.wav", model_factory=factory)
        self.assertEqual(segments, ["cpu speech"])
        self.assertEqual(calls, [("cuda", "float16"), ("cpu", "int8")])

    def test_whisper_cuda_failure_during_lazy_iteration(self):
        from unittest.mock import patch
        from film_runtime import transcribe_segments

        calls = []

        class Whisper:
            def __init__(self, device):
                self.device = device
            def transcribe(self, *_args, **_kwargs):
                if self.device == "cuda":
                    def lazy():
                        raise RuntimeError("cublas64_12.dll missing while decoding")
                        yield "never"
                    return lazy(), None
                return iter(["word times"]), None

        def factory(_name, **kwargs):
            calls.append(kwargs["device"])
            return Whisper(kwargs["device"])

        with patch("film_runtime._cuda_dll_present", return_value=True):
            segments = transcribe_segments("test.wav", model_factory=factory)
        self.assertEqual(segments, ["word times"])
        self.assertEqual(calls, ["cuda", "cpu"])

    def test_whisper_missing_cuda_dll_goes_straight_to_cpu(self):
        from unittest.mock import patch
        from film_runtime import transcribe_segments
        calls = []

        class Whisper:
            def transcribe(self, *_args, **_kwargs):
                return iter(["cpu subtitle"]), None

        def factory(_name, **kwargs):
            calls.append(kwargs["device"])
            return Whisper()

        with patch("film_runtime._cuda_dll_present", return_value=False):
            self.assertEqual(
                transcribe_segments("test.wav", model_factory=factory),
                ["cpu subtitle"],
            )
        self.assertEqual(calls, ["cpu"])

    def test_model_validation_rejects_unverified_xml(self):
        from film_runtime import _verify_cascade
        self.assertFalse(_verify_cascade(b"<?xml version='1.0'?><opencv_storage/>"))
        self.assertFalse(_verify_cascade(b"x" * 930127))

    def test_missing_cascade_downloads_into_local_cache(self):
        import tempfile
        from unittest.mock import patch
        from types import SimpleNamespace
        from film_runtime import locate_cascade, CASCADE_NAME
        from io import BytesIO
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            cv2_stub = SimpleNamespace(
                __file__=str(base / "cv2" / "__init__.py"),
                data=SimpleNamespace(haarcascades=str(base / "missing_data"))
            )
            with patch("film_runtime.urlopen", return_value=BytesIO(b"model")) as fetch:
                with patch("film_runtime._verify_cascade", return_value=True):
                    result = locate_cascade(cv2_stub, base / "cache")
            self.assertEqual(result.name, CASCADE_NAME)
            self.assertEqual(result.read_bytes(), b"model")
            fetch.assert_called_once()

    def test_offline_cascade_download_fails_cleanly(self):
        import tempfile
        from unittest.mock import patch
        from types import SimpleNamespace
        from film_runtime import locate_cascade
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            stub = SimpleNamespace(
                __file__=str(base / "cv2" / "__init__.py"),
                data=SimpleNamespace(haarcascades=str(base / "missing_data"))
            )
            with patch("film_runtime.urlopen", side_effect=OSError("network blocked")):
                with self.assertRaisesRegex(OSError, "network blocked"):
                    locate_cascade(stub, base / "cache")


if __name__ == "__main__":
    unittest.main()
