import unittest

from core.streamer_export import ASPECT_PRESETS, export_settings, intermediate_encoder_args


class StreamerExportTests(unittest.TestCase):
    def test_format_dimensions_are_even_and_distinct(self):
        for ratio in ASPECT_PRESETS:
            with self.subTest(ratio=ratio):
                cfg = export_settings({"output_ratio": ratio})
                self.assertEqual(cfg["width"] % 2, 0)
                self.assertEqual(cfg["height"] % 2, 0)
                self.assertGreater(cfg["height"], 0)
        self.assertEqual(
            (export_settings({"output_ratio": "5:4"})["width"],
             export_settings({"output_ratio": "5:4"})["height"]),
            (1350, 1080),
        )

    def test_4k_9_by_16(self):
        self.assertEqual(
            (export_settings({"output_ratio": "9:16", "output_size": "2160"})["width"],
             export_settings({"output_ratio": "9:16", "output_size": "2160"})["height"]),
            (2160, 3840),
        )

    def test_bad_options_rejected(self):
        for bad in [
            {"output_ratio": "1:0"}, {"output_size": "999"},
            {"output_fps": "120"}, {"motion_mode": "rm -rf"},
            {"output_quality": "lossless"},
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                export_settings(bad)

    def test_intermediate_encoding_no_ultrafast(self):
        gpu = intermediate_encoder_args(["-c:v", "h264_nvenc"], "ultra")
        cpu = intermediate_encoder_args(["-c:v", "libx264"], "ultra")
        self.assertIn("h264_nvenc", gpu)
        self.assertIn("libx264", cpu)
        self.assertNotIn("ultrafast", cpu)
        self.assertNotIn("23", cpu)


if __name__ == "__main__":
    unittest.main()
