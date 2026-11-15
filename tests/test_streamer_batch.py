import tempfile
import unittest
from pathlib import Path

from webjs.streamer_batch import get_cached_section


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download_video_section(self, url, start, end, path, resolution):
        self.calls.append((url, start, end, resolution))
        Path(path).write_bytes(b"test-mp4-" + bytes(12_000))
        return path


class StreamerBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.url = "https://www.youtube.com/watch?v=test123"
        self.sections = [
            {"start_time": "00:01:00,000", "end_time": "00:01:30,000"},
            {"start_time": "00:02:00,000", "end_time": "00:02:30,000"},
            {"start_time": "00:03:00,000", "end_time": "00:03:30,000"},
            {"start_time": "00:04:00,000", "end_time": "00:04:30,000"},
        ]
        self.downloader = FakeDownloader()

    def test_four_sections_have_correct_unique_ranges(self):
        files = [get_cached_section(self.downloader, self.url, self.sections, i, self.root, "best") for i in range(4)]
        self.assertEqual(len(set(files)), 4)
        self.assertTrue(all(p.stat().st_size > 10_000 for p in files))
        self.assertEqual(len(self.downloader.calls), 4)
        self.assertEqual(self.downloader.calls[2][1:3], ("00:03:00.000", "00:03:30.000"))
        # A second render in the same batch must reuse the matching cached segment.
        get_cached_section(self.downloader, self.url, self.sections, 2, self.root, "best")
        self.assertEqual(len(self.downloader.calls), 4)

    def test_mismatched_timestamp_invalidates_cache(self):
        get_cached_section(self.downloader, self.url, self.sections, 0, self.root, "best")
        updated = [dict(s) for s in self.sections]
        updated[0]["start_time"] = "00:01:05,000"
        get_cached_section(self.downloader, self.url, updated, 0, self.root, "best")
        self.assertEqual(len(self.downloader.calls), 2)

    def test_incomplete_file_is_redownloaded(self):
        path = get_cached_section(self.downloader, self.url, self.sections, 0, self.root, "best")
        path.write_bytes(b"broken")
        get_cached_section(self.downloader, self.url, self.sections, 0, self.root, "best")
        self.assertEqual(len(self.downloader.calls), 2)

    def test_reject_invalid_section_index(self):
        with self.assertRaises(ValueError):
            get_cached_section(self.downloader, self.url, self.sections, 4, self.root, "best")


if __name__ == "__main__":
    unittest.main()
