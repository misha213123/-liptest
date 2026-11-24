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
        self.assertEqual(upscale[upscale.index("-s") + 1], "4")
        self.assertEqual(upscale[upscale.index("--realesrgan-model") + 1], "realesrgan-plus")
        self.assertIn("rife", rife)
        self.assertEqual(rife[rife.index("-m") + 1], "2")
        self.assertEqual(rife[rife.index("--rife-model") + 1], "rife-v4.26")
        self.assertEqual(rife[rife.index("--scene-thresh") + 1], "20")
        self.assertEqual(rife[rife.index("-i") + 1], str(steps[0][2]))
        self.assertTrue(all(isinstance(arg, str) for arg in upscale + rife))

    def test_native_model_scales_and_required_files(self):
        from film_video2x import upscale_factor, required_model_files
        self.assertEqual(upscale_factor("realesrgan-plus"), 4)
        self.assertEqual(upscale_factor("realesr-animevideov3"), 2)
        self.assertEqual(upscale_factor("anime4k-v4-a+a"), 1)
        plus = [str(p).replace("\\", "/") for p in required_model_files(
            "realesrgan-plus", 2
        )]
        self.assertIn("models/realesrgan/realesrgan-plus-x4.param", plus)
        self.assertIn("models/realesrgan/realesrgan-plus-x4.bin", plus)
        self.assertIn("models/rife/rife-v4.26/flownet.param", plus)
        self.assertNotIn("models/realesrgan/realesrgan-plus-x2.param", plus)

    def test_video2x_resources_root_and_asset_validation(self):
        import tempfile
        from film_video2x import resources_root, validate_model_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe_dir = root / "bin"
            exe_dir.mkdir()
            exe = exe_dir / "video2x.exe"
            exe.write_bytes(b"cli")
            self.assertEqual(resources_root(str(exe)), exe_dir)
            with self.assertRaisesRegex(RuntimeError, "realesrgan-plus-x4.param"):
                validate_model_files(str(exe), "realesrgan-plus", 1)
            models_dir = root / "models" / "realesrgan"
            models_dir.mkdir(parents=True)
            for ext in (".param", ".bin"):
                (models_dir / ("realesrgan-plus-x4" + ext)).write_bytes(b"model")
            self.assertEqual(resources_root(str(exe)), root)
            self.assertEqual(validate_model_files(str(exe), "realesrgan-plus", 1), root)

    def test_animevideov3_keeps_x2(self):
        from film_video2x import build_steps
        cmd = build_steps(
            "video2x.exe", Path("source.mp4"), Path("output"),
            "realesr-animevideov3", 1, 1080, 1920,
        )[0][1]
        self.assertEqual(cmd[cmd.index("-s") + 1], "2")

    def test_preserve_native_crop_for_realesrgan_plus(self):
        from film_video2x import intermediate_dimensions
        # 720p 16:9 cropped to 9:16 is about 404x720.
        # This must not be reduced to 270x480 before model inference.
        self.assertEqual(
            intermediate_dimensions(404, 720, 1080, 1920, "realesrgan-plus"),
            (404, 720),
        )
        self.assertEqual(
            intermediate_dimensions(404, 720, 2160, 3840, "realesrgan-plus"),
            (540, 960),
        )

    def test_bounded_intermediate_for_larger_source(self):
        from film_video2x import intermediate_dimensions
        w, h = intermediate_dimensions(
            1080, 1920, 1080, 1920, "realesrgan-plus"
        )
        self.assertGreaterEqual(w, 270)
        self.assertLessEqual(w, 410)
        self.assertGreaterEqual(h, 480)
        self.assertLessEqual(h, 730)
        # No processing regressions for non-neural or RIFE-only exports.
        self.assertEqual(
            intermediate_dimensions(404, 720, 1080, 1920, "off"),
            (1080, 1920),
        )

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


class FilmCaptionAndGradeTests(unittest.TestCase):
    def test_five_styles_use_real_ass_formatting(self):
        from types import SimpleNamespace as NS
        from film_captions import subtitle_ass, STYLES
        words = [NS(start=0, end=.34, word="hello"), NS(start=.34, end=.82, word="world")]
        segments = [NS(start=0, end=.82, text="hello world", words=words)]
        self.assertEqual(set(STYLES), {"bold", "karaoke", "cinema", "minimal", "boxed"})
        for name in STYLES:
            text, count = subtitle_ass(segments, 360, 640, name, 78)
            self.assertEqual(count, 1)
            self.assertIn("[V4+ Styles]", text)
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:00.82", text)
            if name == "karaoke":
                self.assertIn(r"{\kf34}", text)
                self.assertIn(r"{\kf48}", text)
            if name == "bold":
                self.assertIn("HELLO WORLD", text)
            if name == "boxed":
                self.assertIn("1,0,0,0,100,100,0,0,3,", text)

    def test_caption_style_and_position_validation(self):
        from film_captions import validate, subtitle_ass
        self.assertEqual(validate("cinema", 75), ("cinema", 75))
        with self.assertRaises(ValueError):
            subtitle_ass([], 1080, 1920, "not-a-template", 78)
        for pos in (0, 49, 91, 200):
            with self.assertRaises(ValueError):
                validate("bold", pos)

    def test_real_color_filters_for_preview_and_render(self):
        from film_filters import color_filters, PRESETS
        self.assertEqual(len(PRESETS), 6)
        self.assertEqual(color_filters({"enhance": False}), [])
        warm = dict(PRESETS["warm"])
        warm["color_tone"] = warm.pop("tone")
        self.assertIn("colorbalance=", ",".join(color_filters(warm)))
        self.assertIn("colorbalance=", ",".join(color_filters(warm, preview=True)))
        self.assertIn("gamma=1.050", ",".join(color_filters(warm)))
        self.assertNotIn("colorbalance", ",".join(color_filters({"color_tone":"neutral"})))
        with self.assertRaises(ValueError):
            color_filters({"color_tone":"invalid"})


class FilmThumbnailTests(unittest.TestCase):
    def test_midpoint_frame_preserves_ratio_and_color(self):
        import tempfile
        from unittest.mock import patch
        import film_preview

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            inputs = base / "inputs"
            inputs.mkdir()
            filename = "0123456789abcdef01234567.mp4"
            (inputs / filename).write_bytes(b"fake-video")
            destination = base / "thumbnail.jpg"
            recorded = []
            def fake_ffmpeg(command, timeout=0):
                recorded.extend(command)
                destination.write_bytes(b"\xff\xd8" + b"\x00" * 800)
            with patch.object(film_preview, "INPUT_DIR", inputs), \
                 patch.object(film_preview, "probe", return_value={
                     "width": 1280, "height": 720,
                     "duration": 60.0, "fps": 25.0
                 }), \
                 patch.object(film_preview, "run", side_effect=fake_ffmpeg):
                result = film_preview.render_preview({
                    "input_id": filename,
                    "start": 0, "end": 10,
                    "preview_position": 50,
                    "ratio": "9:16",
                    "face_tracking": False,
                    "color_tone": "warm",
                }, destination)
            self.assertTrue(result["ok"])
            self.assertEqual(result["at"], 5)
            self.assertEqual((result["width"], result["height"]), (360, 640))
            self.assertEqual(result["face_detected"], False)
            self.assertEqual(recorded[recorded.index("-ss") + 1], "5.0")
            filters = recorded[recorded.index("-vf") + 1]
            self.assertIn("crop=404:720", filters)
            self.assertIn("scale=360:640", filters)
            self.assertIn("colorbalance=", filters)

    def test_invalid_frame_position_does_not_process(self):
        import tempfile
        from unittest.mock import patch
        import film_preview
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            inputs = base / "inputs"
            inputs.mkdir()
            name = "0123456789abcdef01234567.mp4"
            (inputs / name).write_bytes(b"mock")
            with patch.object(film_preview, "INPUT_DIR", inputs), \
                 patch.object(film_preview, "probe", return_value={
                     "width": 1280, "height": 720,
                     "duration": 60, "fps": 25
                 }):
                with self.assertRaisesRegex(ValueError, "Позиция"):
                    film_preview.render_preview({
                        "input_id": name, "start": 0, "end": 10,
                        "preview_position": 500
                    }, base / "frame.jpg")


if __name__ == "__main__":
    unittest.main()
