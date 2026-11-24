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


class FilmVideo2XWatchdogTests(unittest.TestCase):
    def test_hard_first_byte_timeout_does_not_reset_from_false_log_percentages(self):
        from film_video2x import stall_reason
        started=100.0
        self.assertIsNone(stall_reason(160, started, 159, 0, 180, 240))
        # Even if misleading logs have "100%" and last activity was recent,
        # the zero-byte 180s watchdog must still trip.
        message=stall_reason(280, started, 279, 0, 180, 240)
        self.assertIn("180 секунд", message)
        self.assertIsNone(stall_reason(280, started, 279, 1024, 180, 240))
        self.assertIn("не продвигает",stall_reason(390,started,140,2048,180,240))


class FilmFreeAIEnhancementPipelineTests(unittest.TestCase):
    def test_neural_then_motion_then_caption_filter_order(self):
        from film_render import ai_detail_finish_filters
        from pathlib import Path
        filters = ai_detail_finish_filters(
            30.0, 60.0, True, Path("subtitle.ass")
        )
        self.assertIn("minterpolate=fps=60", filters[0])
        self.assertIn("mi_mode=mci", filters[0])
        self.assertTrue(filters[1].startswith("ass="))
        self.assertEqual(filters[-1], "format=yuv420p")
        self.assertEqual(
            ai_detail_finish_filters(60, 60, False), ["format=yuv420p"]
        )
        self.assertEqual(
            ai_detail_finish_filters(30, 60, False),
            ["fps=60", "format=yuv420p"],
        )

    def test_quality_models_use_supported_open_source_names(self):
        from film_ai_detail import MODELS, ai_source_dimensions
        self.assertIn("realesrgan-x4plus", MODELS)
        self.assertIn("realesrnet-x4plus", MODELS)
        self.assertEqual(ai_source_dimensions(404, 720), (404, 720))
        self.assertEqual(ai_source_dimensions(900, 720), (900, 720))

    def test_ffmpeg_model_first_then_60fps_and_subtitles(self):
        import shutil
        import subprocess
        import tempfile
        from film_render import ai_detail_finish_filters
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg not installed in CI")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            ass = directory/"test.ass"
            ass.write_text(
                "[Script Info]\nScriptType: v4.00+\nPlayResX: 96\nPlayResY: 64\n"
                "[V4+ Styles]\n"
                "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
                "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
                "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
                "Alignment,MarginL,MarginR,MarginV,Encoding\n"
                "Style: Default,Arial,11,&H00FFFFFF,&H00FFFFFF,&H00000000,"
                "&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,8,8,8,1\n"
                "[Events]\n"
                "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
                "Dialogue: 0,0:00:00.05,0:00:00.60,Default,,0,0,0,,TEST\n",
                encoding="utf-8",
            )
            # The exact execution on Windows uses the same filter order
            # after Real-ESRGAN has finished at the original 30fps rate.
            # Test FFmpeg rendering without a real GPU/Vulkan dependency.
            from film_render import _ass_filter
            filters = ai_detail_finish_filters(30, 60, True, ass)
            command=[
                ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
                "-f","lavfi","-i","testsrc2=size=96x64:rate=30:duration=.8",
                "-vf",",".join(filters),"-frames:v","43","-f","null","-",
            ]
            result=subprocess.run(command,capture_output=True,text=True,timeout=50)
            self.assertEqual(result.returncode,0,result.stderr[:1300])


class FilmNeuralDetailTests(unittest.TestCase):
    def test_free_ai_single_frame_preview_is_explicit_and_preserves_target(self):
        import tempfile
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        from film_ai_detail import restore_preview_frame

        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            source=folder/"original-preview.jpg"
            source.write_bytes(b"original-jpeg-for-test"*40)
            exe=folder/"realesrgan-ncnn-vulkan.exe"
            exe.write_bytes(b"not-a-real-binary")
            models=folder/"models"
            models.mkdir()

            def fake_ffmpeg(cmd,timeout):
                calls.append(cmd)
                dest=Path(cmd[-1])
                dest.write_bytes(b"processed-"+bytes(dest.suffix,"ascii")*300)

            def fake_ncnn(cmd,**kw):
                calls.append(cmd)
                output=Path(cmd[cmd.index("-o")+1])
                output.write_bytes(b"upscaled-frame-by-model"*40)
                return NS(returncode=0)

            with patch("film_ai_detail.require_binary", return_value=(exe,models)), \
                 patch("film_ai_detail.run_cmd",side_effect=fake_ffmpeg), \
                 patch("film_ai_detail.subprocess.run",side_effect=fake_ncnn):
                restore_preview_frame(source,"ffmpeg",360,640,
                                      model="realesrnet-x4plus",tile=32)
            self.assertTrue(source.is_file())
            self.assertNotIn(b"original",source.read_bytes())
            ai_cmd=next(cmd for cmd in calls if "-n" in cmd)
            self.assertEqual(ai_cmd[ai_cmd.index("-n")+1],"realesrnet-x4plus")
            self.assertEqual(ai_cmd[ai_cmd.index("-t")+1],"32")
            self.assertTrue(any("scale=360:640:flags=lanczos" in
                                cmd for row in calls for cmd in row))
            with self.assertRaises(ValueError):
                restore_preview_frame(source,"ffmpeg",360,640,
                                      model="unknown")

    def test_native_resolution_kept_for_720p_source_crops(self):
        from film_ai_detail import ai_source_dimensions
        self.assertEqual(ai_source_dimensions(404,720),(404,720))
        self.assertEqual(ai_source_dimensions(900,720),(900,720))
        self.assertEqual(ai_source_dimensions(1920,1080),(1280,720))
        for values in ((0,720),(-1,1080)):
            with self.assertRaises(ValueError):
                ai_source_dimensions(*values)

    def test_ncnn_requires_opt_in_and_valid_tile(self):
        from unittest.mock import patch
        import tempfile
        import film_ai_detail
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)
            fake=parent/"realesrgan-ncnn-vulkan.exe"
            fake.write_bytes(b"fake")
            models=parent/"models"
            models.mkdir()
            for name in film_ai_detail.MODELS:
                for suffix in ("param","bin"):
                    (models/(name+"."+suffix)).write_bytes(b"fake")
            with patch.dict("os.environ", {"AI_RESTORE_NCNN_BIN":str(fake)}):
                exe, found=film_ai_detail.require_binary()
                self.assertEqual(exe,fake)
                self.assertEqual(found,models)
                with self.assertRaises(ValueError):
                    film_ai_detail.restore_clip(parent/"fake.mp4",parent,
                        "ffmpeg", 31,60, lambda *_:None)
                with self.assertRaises(ValueError):
                    film_ai_detail.restore_clip(parent/"fake.mp4",parent,
                        "ffmpeg", 5,60, lambda *_:None, tile=2)
        with patch("film_ai_detail.find_binary",return_value=(None,None)):
            with self.assertRaises(RuntimeError):
                film_ai_detail.require_binary()

    def test_ncnn_processes_frames_and_restores_audio(self):
        import tempfile
        from unittest.mock import patch
        import film_ai_detail
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"film_prepared.mp4"
            source.write_bytes(b"fake source")
            binary=root/"ncnn.exe"
            binary.write_bytes(b"x")
            models=root/"models"
            models.mkdir()
            output=root/"ai_detail_restored.mp4"
            commands=[]
            class Process:
                pid=111
                def poll(self):return 0
            def fake_run(args,timeout):
                commands.append(args)
                target=Path(args[-1])
                if "frame_%06d.png" in str(target):
                    folder=target.parent
                    folder.mkdir(exist_ok=True)
                    for index in range(1,4):
                        (folder/f"frame_{index:06d}.png").write_bytes(b"png")
                elif target.name=="ai_detail_restored.mp4":
                    target.write_bytes(b"mp4"+b"0"*101000)
            def fake_popen(args,**kw):
                commands.append(args)
                folder=Path(args[args.index("-o")+1])
                folder.mkdir(exist_ok=True)
                for index in range(1,4):
                    (folder/f"frame_{index:06d}.png").write_bytes(b"png")
                return Process()
            with patch("film_ai_detail.require_binary",return_value=(binary,models)), \
                 patch("film_ai_detail.run_cmd",side_effect=fake_run), \
                 patch("film_ai_detail.subprocess.Popen",side_effect=fake_popen):
                got=film_ai_detail.restore_clip(
                    source,root,"ffmpeg",3.0,60.0,lambda *_:None
                )
            self.assertEqual(got,output)
            self.assertTrue(output.is_file())
            model_command=next(row for row in commands if "-n" in row)
            self.assertEqual(model_command[model_command.index("-t")+1],"64")
            self.assertEqual(model_command[model_command.index("-s")+1],"2")
            self.assertTrue(any("-map" in row and "1:a:0?" in row for row in commands))
            self.assertTrue(any(
                "-vf" in row and "scale=1920:1080:flags=lanczos" in row
                for row in commands
            ))
            self.assertFalse((root/"ai_detail_in").exists())
            self.assertFalse((root/"ai_detail_out").exists())



class FilmTranscriptCachingTests(unittest.TestCase):
    def test_formatting_rerenders_reuse_api_transcript(self):
        import tempfile
        from types import SimpleNamespace as NS
        from film_transcript_cache import transcribe_cached
        from film_captions import subtitle_ass
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"episode.mp4"
            source.write_bytes(b"movie-data")
            count={"calls":0}
            def producer():
                count["calls"]+=1
                return [
                    NS(start=.1,end=.8,text="Привет, мир!",words=[
                        NS(start=.1,end=.4,word="Привет,"),
                        NS(start=.41,end=.8,word="мир!"),
                    ]),
                ]
            call=lambda:transcribe_cached(
                source, 5.0, 10.0, "openai_max", "medium", "ru",
                producer, cache_dir=Path(tmp)/"cache",
            )
            raw=call()
            self.assertEqual(count["calls"],1)
            clean=call()
            self.assertEqual(count["calls"],1)
            self.assertEqual(clean[0].words[0].word,"Привет,")
            a,n=subtitle_ass(raw,360,640,"bold",78,0,1,False)
            b,m=subtitle_ass(clean,360,640,"minimal",78,0,8,True)
            self.assertEqual(n,2)
            self.assertEqual(m,1)
            self.assertIn("Привет мир",b)
            self.assertNotIn("Привет,",b)
            self.assertIn("ПРИВЕТ,",a)
            # A different audio excerpt requires a different cache key.
            transcribe_cached(
                source, 6, 10, "openai_max", "medium", "ru",
                producer, cache_dir=Path(tmp)/"cache",
            )
            self.assertEqual(count["calls"],2)


class FilmBeautySmartColorsTests(unittest.TestCase):
    def test_bounded_skin_and_smart_color_controls(self):
        from film_beauty import settings, active
        self.assertFalse(active(settings({})))
        natural = settings({
            "face_beauty": True, "beauty_skin": 42, "beauty_tone": 38,
            "smart_colors": True, "smart_color_strength": 55,
            "smart_clarity": 27,
        })
        self.assertTrue(active(natural))
        self.assertAlmostEqual(natural["skin"], .42)
        self.assertAlmostEqual(natural["tone"], .38)
        self.assertAlmostEqual(natural["colors"], .55)
        for bad in [
            {"beauty_skin": -1}, {"beauty_tone": 101},
            {"smart_color_strength": "nan"},
            {"smart_clarity": "inf"}, {"face_beauty": "yes"},
        ]:
            with self.assertRaises(ValueError):
                settings(bad)

    def test_skin_mask_keeps_eyes_and_background_untouched(self):
        import cv2
        import numpy as np
        from film_beauty import beauty_face
        rng = np.random.default_rng(42)
        # Synthetic face-colored BGR region with modest noise; avoid requiring
        # a real portrait/identity in the public GitHub test suite.
        frame = np.clip(
            np.full((128, 128, 3), [120, 152, 185], dtype=np.int16)
            + rng.integers(-18, 19, (128, 128, 3)), 0, 255
        ).astype(np.uint8)
        before = frame.copy()
        beauty_face(frame, (15, 12, 96, 100), cv2, np, 1.0, .8)
        # An off-face pixel is never retouched.
        self.assertTrue(np.array_equal(frame[3:8, 3:8], before[3:8, 3:8]))
        # Foreground cheek pixels change, but eyes and lips retain structure.
        cheek_region = np.abs(
            frame[63:76, 34:46].astype(int) - before[63:76, 34:46].astype(int)
        )
        self.assertGreater(int(cheek_region.sum()), 5)
        eye_region = np.abs(
            frame[45:52, 43:75].astype(int) - before[45:52, 43:75].astype(int)
        )
        # Soft mask may feather slightly near the eye boundary, but the
        # protected eye band is much less affected than cheek skin.
        self.assertLess(eye_region.mean(), cheek_region.mean())

    def test_smart_colors_changes_actual_pixels_and_preview(self):
        import cv2
        import numpy as np
        import tempfile
        from film_beauty import smart_colors, process_preview_image
        source = np.tile(
            np.linspace(48, 170, 96, dtype=np.uint8), (64, 1)
        )
        frame = np.stack((source, source, np.clip(source + 8,0,255)), axis=-1)
        updated = smart_colors(frame.copy(), cv2, np, .85, .35)
        self.assertEqual(updated.shape, frame.shape)
        self.assertGreater(np.abs(updated.astype(int) - frame.astype(int)).sum(), 300)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"thumb.jpg"
            self.assertTrue(cv2.imwrite(str(path), frame))
            original = path.read_bytes()
            summary = process_preview_image(path, {
                "smart_colors": True, "smart_color_strength": 85,
                "smart_clarity": 35,
            }, Path(tmp))
            self.assertTrue(summary["enabled"])
            self.assertNotEqual(path.read_bytes(), original)
            self.assertEqual(summary["faces"], 0)

    def test_face_detector_is_used_only_for_beauty(self):
        import cv2
        import numpy as np
        from film_beauty import VideoProcessor, settings
        class FakeDetector:
            def __init__(self): self.calls=0
            def detectMultiScale(self, *args, **kwargs):
                self.calls+=1
                return np.array([[17, 13, 76, 88]], dtype=np.int32)
        detector=FakeDetector()
        processor=VideoProcessor(
            settings({"face_beauty":True,"beauty_skin":70,"beauty_tone":35}),
            Path("."), cv2=cv2, np=np, detector=detector,
        )
        frame=np.full((128,128,3),[120,152,185],dtype=np.uint8)
        processor.process(frame.copy())
        self.assertGreaterEqual(detector.calls,1)
        self.assertGreater(processor.faces_seen,0)
        no_detector=VideoProcessor(
            settings({"smart_colors":True,"smart_color_strength":40}),
            Path("."),cv2=cv2,np=np,
        )
        no_detector.process(frame.copy())
        self.assertEqual(no_detector.faces_seen,0)

    def test_actual_ffmpeg_beauty_clip_has_expected_frames(self):
        import shutil
        import subprocess
        import tempfile
        from film_beauty import process_clip, settings
        ffmpeg=shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            original=folder/"original.mp4"
            altered=folder/"skin-and-colors.mp4"
            src_cmd=[
                ffmpeg,"-hide_banner","-loglevel","error","-y",
                "-f","lavfi","-i","testsrc2=size=160x90:rate=12:duration=1.0",
                "-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=1.0",
                "-c:v","mpeg4","-c:a","aac","-shortest",str(original),
            ]
            result=subprocess.run(src_cmd,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr[:1000])
            captured=[]
            converted,info=process_clip(
                original,altered,ffmpeg,.10,.55,12.0,160,90,
                settings({"smart_colors":True,"smart_color_strength":50,
                          "smart_clarity":20}),
                folder, report=lambda *args: captured.append(args),
            )
            self.assertEqual(converted,altered)
            self.assertTrue(converted.is_file())
            self.assertGreater(info["frames"],3)
            self.assertTrue(captured)
            # The pipeline retains source audio by muxing the original later.
            merged=folder/"final.mp4"
            command=[
                ffmpeg,"-hide_banner","-loglevel","error","-y",
                "-i",str(converted),"-ss","0.10","-i",str(original),
                "-t","0.55","-map","0:v:0","-map","1:a:0?",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",
                str(merged),
            ]
            result=subprocess.run(command,capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stderr[:1000])
            self.assertTrue(merged.is_file())
            self.assertGreater(merged.stat().st_size,2500)


class FilmSmoothVividPresetTests(unittest.TestCase):
    def test_smooth_vivid_is_real_saturated_warm_grade(self):
        from film_filters import PRESETS, color_filters
        params = PRESETS["smooth_vivid"]
        self.assertGreater(params["saturation"], 1.2)
        self.assertGreater(params["contrast"], 1.1)
        self.assertGreater(params["gamma"], 1.0)
        self.assertEqual(params["tone"], "warm")
        job = {
            "enhance": True, **{k: v for k, v in params.items() if k != "tone"},
            "color_tone": params["tone"], "denoise":34,
            "artifact_reduction":22, "microdetail":28, "sharpen":38,
        }
        filters = ",".join(color_filters(job))
        self.assertIn("hqdn3d=", filters)
        self.assertIn("deblock=", filters)
        self.assertIn("colorbalance=", filters)
        self.assertIn("saturation=1.290", filters)
        self.assertIn("contrast=1.190", filters)

    def test_true_motion_compensation_not_frame_duplication(self):
        from film_render import optical_motion_filter
        result = optical_motion_filter(30, 60, True)
        self.assertIn("minterpolate=fps=60", result)
        self.assertIn("mi_mode=mci", result)
        self.assertIn("scd=fdiff", result)
        self.assertEqual(optical_motion_filter(30, 60, False), "")
        self.assertEqual(optical_motion_filter(60, 60, True), "")

    def test_ffmpeg_smooth_30_to_60_filter_runs_on_real_frames(self):
        import shutil
        import subprocess
        from film_render import optical_motion_filter
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed in CI environment")
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi",
            "-i", "testsrc2=size=96x64:rate=30:duration=0.8",
            "-vf", ",".join([
                optical_motion_filter(30, 60, True),
                "scale=144:96:flags=lanczos",
                "format=yuv420p",
            ]),
            "-f", "framehash", "-"
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr[:1400])
        # A real motion interpolator emits ~2x frames at the requested 60 Hz,
        # not a metadata-only '60 FPS' flag on the original 30 FPS video.
        self.assertIn("1/60", result.stdout)
        data_rows = [
            line for line in result.stdout.splitlines()
            if line and not line.startswith("#")
        ]
        self.assertGreaterEqual(len(data_rows), 40)


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

    def test_caption_word_grouping_crosses_whisper_segment_boundaries(self):
        from types import SimpleNamespace as NS
        from film_captions import subtitle_ass
        segments = [
            NS(words=[
                NS(start=0.10, end=0.40, word="Мы,"),
                NS(start=0.41, end=0.72, word="сегодня"),
                NS(start=0.73, end=1.04, word="снова."),
            ]),
            NS(words=[
                NS(start=1.05, end=1.33, word="вместе!"),
                NS(start=1.34, end=1.68, word="Привет"),
            ]),
        ]
        whole, count = subtitle_ass(segments, 360, 640, "minimal", 78, 0, 4, True)
        self.assertEqual(count, 2)
        self.assertIn("Мы сегодня снова вместе", whole)
        self.assertNotIn("снова.", whole)
        self.assertNotIn("вместе!", whole)
        self.assertIn("0:00:00.10,0:00:01.33", whole)
        short, count = subtitle_ass(segments, 360, 640, "minimal", 78, 0, 1, True)
        self.assertEqual(count, 5)
        self.assertIn("0:00:00.10,0:00:00.40", short)
        whole, count = subtitle_ass(segments, 360, 640, "minimal", 78, 0, 8, True)
        self.assertEqual(count, 1)

    def test_caption_punctuation_can_be_enabled_or_removed(self):
        from types import SimpleNamespace as NS
        from film_captions import subtitle_ass, caption_text
        words = [
            NS(word="Привет,", start=0.0, end=.25),
            NS(word="мир!", start=.25, end=.60),
            NS(word="кто-то", start=.61, end=.9),
        ]
        lines = [NS(words=words)]
        original, _ = subtitle_ass(lines, 1080, 1920, "karaoke", 78)
        cleaned, _ = subtitle_ass(lines, 1080, 1920, "karaoke", 78, 0, 3, True)
        self.assertIn("Привет,", original)
        self.assertNotIn("Привет,", cleaned)
        self.assertNotIn("мир!", cleaned)
        self.assertIn(r"{\kf", cleaned)
        self.assertIn("кто-то", cleaned)
        self.assertEqual(caption_text("«Дёсна.»", True), "Дёсна")
        for bad in (0, 9, -1, 100):
            with self.assertRaises(ValueError):
                subtitle_ass(lines, 1080, 1920, "bold", 78, 0, bad)

    def test_caption_pauses_split_even_when_word_limit_large(self):
        from types import SimpleNamespace as NS
        from film_captions import subtitle_ass
        seg = [NS(words=[
            NS(word="Один", start=.1, end=.3),
            NS(word="Два", start=.31, end=.5),
            NS(word="Три", start=2., end=2.2),
        ])]
        caption, n = subtitle_ass(seg, 360, 640, "bold", 78, 0, 8, True)
        self.assertEqual(n, 2)
        self.assertIn("ОДИН ДВА", caption)
        self.assertIn("ТРИ", caption)

    def test_caption_audio_offset_moves_all_words(self):
        from types import SimpleNamespace as NS
        from film_captions import subtitle_ass
        words = [NS(start=.5, end=.9, word="спасибо")]
        segments = [NS(start=.5, end=.9, text="спасибо", words=words)]
        shifted, _ = subtitle_ass(segments, 1080, 1920, "bold", 78, .3)
        early, _ = subtitle_ass(segments, 1080, 1920, "bold", 78, -.2)
        self.assertIn("0:00:00.80,0:00:01.20", shifted)
        self.assertIn("0:00:00.30,0:00:00.70", early)
        with self.assertRaises(ValueError):
            subtitle_ass(segments, 1080, 1920, "bold", 78, 25)

    def test_caption_font_size_and_case_for_all_styles(self):
        from types import SimpleNamespace as NS
        from film_captions import subtitle_ass, caption_size, caption_letter_case
        sample=[NS(start=.2,end=.8,text="Мы Сильные",words=[
            NS(word="Мы",start=.2,end=.45),
            NS(word="Сильные",start=.45,end=.8),
        ])]
        self.assertEqual(caption_size(30),30)
        self.assertEqual(caption_letter_case("LOWER"),"lower")
        for style in ("bold","karaoke","cinema","minimal","boxed"):
            default,_=subtitle_ass(sample,1080,1920,style,78,0,3,False)
            small,_=subtitle_ass(sample,1080,1920,style,40,0,3,False,30,"lower")
            big,_=subtitle_ass(sample,1080,1920,style,90,0,3,False,180,"upper")
            if style == "karaoke":
                self.assertIn("}мы", small)
                self.assertIn("}сильные", small)
                self.assertIn("}МЫ", big)
                self.assertIn("}СИЛЬНЫЕ", big)
            else:
                self.assertIn("мы сильные", small)
                self.assertIn("МЫ СИЛЬНЫЕ", big)
            self.assertNotIn("Мы Сильные", small)
            def size(doc):
                return int(doc.split("Style: Default,")[1].split(",",3)[1])
            self.assertLess(size(small),size(default))
            self.assertGreater(size(big),size(default))
            # ASS bottom margin depends on direct-drag position.
            self.assertNotEqual(small.split("Style: Default,")[1].splitlines()[0],
                                big.split("Style: Default,")[1].splitlines()[0])
        for val in (0,29,181,500):
            with self.assertRaises(ValueError):
                subtitle_ass(sample,1080,1920,"minimal",78,0,3,False,val,"lower")
        with self.assertRaises(ValueError):
            subtitle_ass(sample,1080,1920,"minimal",78,0,3,False,100,"typo")

    def test_strong_color_grading_maxima(self):
        from film_filters import color_filters
        applied=",".join(color_filters({
            "enhance":True, "gamma":1.6, "brightness":.25,
            "saturation":2.5, "contrast":1.8,
        }))
        self.assertIn("gamma=1.600",applied)
        self.assertIn("brightness=0.250",applied)
        self.assertIn("saturation=2.500",applied)
        self.assertIn("contrast=1.800",applied)
        with self.assertRaises(ValueError):
            color_filters({"gamma":"NaN"})

    def test_caption_style_and_position_validation(self):
        from film_captions import validate, subtitle_ass
        self.assertEqual(validate("cinema", 75), ("cinema", 75))
        with self.assertRaises(ValueError):
            subtitle_ass([], 1080, 1920, "not-a-template", 78)
        for pos in (0, 9, 96, 200):
            with self.assertRaises(ValueError):
                validate("bold", pos)

    def test_manual_restoration_sliders_generate_real_filters(self):
        from film_filters import color_filters, restoration_filters
        job = {
            "enhance": True, "artifact_reduction": 45,
            "denoise": 35, "microdetail": 25,
            "sharpen": 55, "film_grain": 10,
            "color_tone": "warm",
        }
        prior, after = restoration_filters(job)
        self.assertTrue(prior[0].startswith("deblock="))
        self.assertTrue(prior[1].startswith("hqdn3d="))
        self.assertTrue(after[0].startswith("unsharp=3:3"))
        self.assertTrue(after[1].startswith("unsharp=5:5"))
        self.assertTrue(after[2].startswith("noise=alls="))
        both = color_filters(job)
        self.assertIn("eq=brightness=", ",".join(both))
        self.assertEqual(both[:2], prior)
        self.assertIn("colorbalance=", ",".join(both))
        self.assertEqual(both[-3:], after)
        self.assertEqual(color_filters({"enhance":False,**job,"enhance":False}), [])
        with self.assertRaises(ValueError):
            restoration_filters({"denoise":"nan"})
        with self.assertRaises(ValueError):
            restoration_filters({"sharpen":"inf"})

    def test_restoration_ffmpeg_filter_graph_when_installed(self):
        import shutil
        import subprocess
        from film_filters import color_filters
        executable = shutil.which("ffmpeg")
        if not executable:
            self.skipTest("FFmpeg not installed in CI environment")
        job = {
            "enhance": True, "artifact_reduction": 35,
            "denoise": 40, "microdetail": 25,
            "sharpen": 45, "film_grain": 12,
            "color_tone": "warm",
        }
        cmd = [
            executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=5:duration=1",
            "-vf", ",".join(color_filters(job)), "-frames:v", "2",
            "-f", "null", "-"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[:1100])

    def test_real_color_filters_for_preview_and_render(self):
        from film_filters import color_filters, PRESETS
        self.assertEqual(len(PRESETS), 9)
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
                recorded.append(command)
                Path(command[-1]).write_bytes(b"\xff\xd8" + b"\x00" * 800)
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
            self.assertEqual(len(recorded), 2)
            self.assertEqual(recorded[0][recorded[0].index("-ss") + 1], "5.0")
            original = recorded[0][recorded[0].index("-vf") + 1]
            filters = recorded[1][recorded[1].index("-vf") + 1]
            self.assertIn("crop=404:720", filters)
            self.assertIn("scale=360:640", filters)
            self.assertNotIn("colorbalance=", original)
            self.assertIn("colorbalance=", filters)
            self.assertTrue(destination.with_name("thumbnail_before.jpg").exists())

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


class FilmOpenAISubtitlesTests(unittest.TestCase):
    def test_key_status_uses_environment_without_exposing_token(self):
        import os
        import tempfile
        from unittest.mock import patch
        from film_openai import find_api_key, availability
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-TEST-NOT-REAL"}, clear=True):
                key, source = find_api_key(Path(tmp))
                self.assertEqual(key, "sk-TEST-NOT-REAL")
                self.assertEqual(source, "OPENAI_API_KEY")
                data = availability(Path(tmp))
                self.assertTrue(data["configured"])
                self.assertNotIn(key, str(data))

    def test_reuses_saved_official_openai_key_but_not_openrouter(self):
        import os
        import json
        import tempfile
        from unittest.mock import patch
        from film_openai import find_api_key
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            directory = Path(tmp)
            config = directory / "config.json"
            config.write_text(json.dumps({
                "ai_providers": {
                    "hook_maker": {
                        "api_key": "sk-openrouter-not-real",
                        "base_url": "https://openrouter.ai/api/v1"
                    },
                    "highlight_finder": {
                        "api_key": "sk-correct-openai-not-real",
                        "base_url": "https://api.openai.com/v1"
                    }
                }
            }), encoding="utf-8")
            key, source = find_api_key(directory)
            self.assertEqual(key, "sk-correct-openai-not-real")
            self.assertEqual(source, "config.ai_providers.highlight_finder")

    def test_cloud_words_convert_to_timed_caption_segments(self):
        from types import SimpleNamespace as NS
        from film_openai import normalise_words
        raw = [
            NS(word="Добрый", start=0.2, end=.53),
            NS(word="день", start=.53, end=.95),
            NS(word="вам", start=1.3, end=1.6),
            NS(word="привет", start=1.7, end=2.0),
        ]
        segments = normalise_words(raw)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "Добрый день вам")
        self.assertEqual(segments[0].start, .2)
        self.assertEqual(segments[0].end, 1.6)
        self.assertEqual(segments[1].words[0].word, "привет")
        from film_captions import subtitle_ass
        result, count = subtitle_ass(segments, 1080, 1920, "karaoke", 78)
        self.assertEqual(count, 2)
        self.assertIn("Dialogue: 0,0:00:00.20,0:00:01.60", result)
        self.assertIn(r"{\kf", result)

    def test_real_openai_request_shape_is_word_timed(self):
        import os
        import tempfile
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        from film_openai import transcribe_openai

        requests = []
        class Transcriptions:
            def create(self, **kwargs):
                requests.append(kwargs)
                self_file = kwargs["file"]
                if self_file.closed:
                    raise AssertionError("Audio stream was closed before the API call.")
                return NS(words=[NS(word="Hello", start=.1, end=.5)])
        class Audio:
            transcriptions = Transcriptions()
        class Client:
            audio = Audio()
        def factory(**kwargs):
            self.assertEqual(kwargs["base_url"], "https://api.openai.com/v1")
            self.assertEqual(kwargs["api_key"], "sk-TEST-NOT-REAL")
            return Client()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "speech.wav"
            file.write_bytes(b"fake wav" + b"\x00" * 2048)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-TEST-NOT-REAL"}, clear=True):
                words = transcribe_openai(file, "en", client_factory=factory, root=Path(tmp))
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0].words[0].start, .1)
        self.assertEqual(requests[0]["model"], "whisper-1")
        self.assertEqual(requests[0]["response_format"], "verbose_json")
        self.assertEqual(requests[0]["timestamp_granularities"], ["word"])
        self.assertEqual(requests[0]["language"], "en")

    def test_failed_api_call_does_not_leak_token(self):
        import os
        import tempfile
        from unittest.mock import patch
        from film_openai import transcribe_openai
        class FakeAPIError(Exception):
            status_code = 401
        class Create:
            def create(self, **kwargs):
                raise FakeAPIError("sk-TEST-NOT-REAL must not appear")
        class Client:
            def __init__(self):
                self.audio = type("Audio", (), {"transcriptions": Create()})()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "audio.wav"
            file.write_bytes(b"\0" * 2000)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-TEST-NOT-REAL"}, clear=True):
                with self.assertRaises(RuntimeError) as ctx:
                    transcribe_openai(file, client_factory=lambda **kwargs: Client(), root=Path(tmp))
        self.assertIn("ключ отклонён", str(ctx.exception))
        self.assertNotIn("sk-TEST", str(ctx.exception))



class FilmOpenAIMaxTests(unittest.TestCase):
    def test_max_text_corrects_1_to_1_but_never_fabricates_timestamps(self):
        from types import SimpleNamespace as NS
        from film_openai_max import align_text_to_timed_words
        words = [
            NS(word="Мама", start=0.1, end=0.4),
            NS(word="мыла", start=0.4, end=0.7),
            NS(word="рамы", start=0.7, end=1.0),
        ]
        base = [NS(words=words)]
        result, stats = align_text_to_timed_words("Мама любила рамы", base)
        flattened = [w for s in result for w in s.words]
        self.assertEqual([w.word for w in flattened], ["Мама", "любила", "рамы"])
        self.assertEqual([w.start for w in flattened], [.1, .4, .7])
        self.assertEqual(stats["corrected_words"], 1)
        result, stats = align_text_to_timed_words("Мама очень сильно мыла рамы", base)
        flattened = [w for s in result for w in s.words]
        self.assertEqual(len(flattened), 3)
        self.assertEqual([w.start for w in flattened], [.1, .4, .7])
        self.assertGreater(stats["unaligned_words"], 0)

    def test_max_model_calls_gpt_and_timing_provider(self):
        import os
        import tempfile
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        from film_openai_max import transcribe_max

        requests = []
        class Transcriptions:
            def create(self, **kwargs):
                requests.append(kwargs)
                return NS(text="Привет, мир!")
        class Client:
            audio = NS(transcriptions=Transcriptions())
        def factory(**kwargs):
            self.assertEqual(kwargs["base_url"], "https://api.openai.com/v1")
            return Client()
        timing = [NS(words=[
            NS(word="Привет", start=.1, end=.45),
            NS(word="мир", start=.5, end=.8)
        ])]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.wav"
            path.write_bytes(b"wave" + b"\x00"*2000)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-NOT-REAL-TEST"}, clear=True), \
                 patch("film_openai_max.transcribe_openai", return_value=timing) as legacy:
                result = transcribe_max(path, "ru", client_factory=factory, root=Path(tmp))
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], "gpt-transcribe")
        self.assertEqual(requests[0]["extra_body"], {"languages": ["ru"]})
        self.assertNotIn("timestamp_granularities", requests[0])
        legacy.assert_called_once()
        self.assertEqual(
            [w.word for segment in result for w in segment.words],
            ["Привет,", "мир!"]
        )

    def test_max_fails_safely_when_timing_api_fails(self):
        import os
        import tempfile
        from types import SimpleNamespace as NS
        from unittest.mock import patch
        from film_openai_max import transcribe_max
        class Transcriptions:
            def create(self, **kwargs):
                return NS(text="Здравствуйте")
        class Client:
            audio = NS(transcriptions=Transcriptions())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.wav"
            path.write_bytes(b"wave" + b"\x00"*2000)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-TEST-NOT-REAL"}, clear=True), \
                 patch("film_openai_max.transcribe_openai", side_effect=RuntimeError("timing unavailable")):
                with self.assertRaisesRegex(RuntimeError, "timing unavailable"):
                    transcribe_max(path, client_factory=lambda **kwargs: Client(), root=Path(tmp))


class FilmHighlightDiscoveryTests(unittest.TestCase):
    def test_highlight_settings_are_bounded(self):
        from film_highlights import validate_settings
        self.assertEqual(validate_settings({})["count"], 6)
        self.assertEqual(validate_settings({"count": 10, "min_duration": 12, "max_duration": 44})["count"], 10)
        for invalid in [
            {"count": 1}, {"count": 13},
            {"min_duration": 1}, {"min_duration": 100},
            {"min_duration": 50, "max_duration": 30},
            {"max_duration": 240}, {"language": "xx"},
        ]:
            with self.assertRaises(ValueError):
                validate_settings(invalid)

    def test_timestamped_transcript_scans_entire_series(self):
        from film_highlights import timestamped_lines
        words=[
            {"start":1.0,"end":1.4,"word":"Начало"},
            {"start":1501.5,"end":1502,"word":"Поворот"},
            {"start":3580.2,"end":3580.5,"word":"Развязка"},
        ]
        rows=timestamped_lines(words,3600)
        self.assertEqual([r["start"] for r in rows],[0,1500,3576])
        self.assertEqual([r["text"] for r in rows],["Начало","Поворот","Развязка"])

    def test_cannot_invent_unspoken_and_out_of_bounds_scene(self):
        from film_highlights import choose_highlights
        words=[{"start":t,"end":t+.4,"word":"сцена"} for t in range(10,200,2)]
        candidates=[
            {"start":20,"end":45,"score":91,"title":"1","reason":"Поворот", "category":"plot_twist"},
            {"start":22,"end":48,"score":90,"title":"2","reason":"Дубль", "category":"tension"},
            {"start":120,"end":150,"score":87,"title":"3","reason":"Юмор", "category":"humor"},
            {"start":210,"end":240,"score":99,"title":"Придумано", "reason":"Нет речи"},
            {"start":182,"end":340,"score":96,"title":"Длинный", "reason":"За пределами"},
            {"start":-2,"end":25,"score":95,"title":"Минус", "reason":"За пределами"},
        ]
        chosen=choose_highlights(candidates, words,240,6,15,60)
        self.assertEqual(len(chosen),2)
        self.assertEqual(chosen[0]["start"],20)
        self.assertEqual(chosen[1]["start"],120)
        self.assertEqual([x["rank"] for x in chosen],[1,2])

    def test_transcription_chunks_reuse_cached_words_without_paid_api(self):
        from film_highlights import transcribe_episode
        from types import SimpleNamespace as NS
        import tempfile
        from unittest.mock import patch
        from film_highlights import AUDIO_CHUNK_SECONDS
        class T:
            def __init__(self):self.calls=0
            def create(self,**kwargs):
                self.calls+=1
                return NS(words=[
                    NS(word="Hello",start=2.0,end=2.3),
                    NS(word="world",start=2.4,end=2.8)
                ])
        trans=T()
        client=NS(audio=NS(transcriptions=trans))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            src=folder/"episode.mp4"
            src.write_bytes(b"fake")
            def fake_run(cmd,timeout=0):
                Path(cmd[-1]).write_bytes(b"RIFF"+b"\x00"*2000)
            with patch("film_highlights.run",side_effect=fake_run):
                words=transcribe_episode(src,AUDIO_CHUNK_SECONDS+20,"en",folder/"cache",client,report=lambda *_:None)
                self.assertEqual(trans.calls,2)
                self.assertEqual(len(words),4)
                self.assertEqual(words[-1]["start"], AUDIO_CHUNK_SECONDS+2.4)
                words_again=transcribe_episode(src,AUDIO_CHUNK_SECONDS+20,"en",folder/"cache",client,report=lambda *_:None)
                self.assertEqual(trans.calls,2)
                self.assertEqual(words_again,words)

    def test_ai_response_is_parsed_as_ranked_candidates(self):
        from types import SimpleNamespace as NS
        from film_highlights import _model_response
        calls=[]
        class Chat:
            def create(self,**kwargs):
                calls.append(kwargs)
                return NS(choices=[NS(message=NS(content='{"clips":[{"start":10,"end":40,"score":85,"title":"Сцена","reason":"Сильный конфликт","category":"tension"}]}'))])
        client=NS(chat=NS(completions=Chat()))
        settings={"min_duration":15,"max_duration":60}
        got=_model_response(client,[{"start":0,"end":48,"text":"Серьёзный разговор"}],settings)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]["score"],85)
        self.assertEqual(calls[0]["model"],"gpt-4.1")
        self.assertEqual(calls[0]["response_format"],{"type":"json_object"})


if __name__ == "__main__":
    unittest.main()
