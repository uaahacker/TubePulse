from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless

from PIL import Image

from ai_studio.exceptions import AssetError
from ai_studio.video.assets import (
    AssetDownloader,
    AssetResolver,
    StockAssetReference,
    validate_public_url,
)
from ai_studio.video.pipeline import VerticalVideoPipeline
from ai_studio.video.subtitles import CaptionStyle, build_caption_cues


class FakeDownloadResponse:
    status_code = 200
    headers = {"Content-Type": "image/jpeg", "Content-Length": "8"}
    text = ""

    def iter_content(self, chunk_size):
        yield b"jpegdata"

    def close(self):
        return None


class FakeDownloadSession:
    def get(self, url, **kwargs):
        return FakeDownloadResponse()


class AssetAndSubtitleTests(TestCase):
    def test_downloader_streams_to_a_unique_final_file(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = AssetDownloader(
                session=FakeDownloadSession(), url_validator=lambda url: None
            )
            result = downloader.download(
                StockAssetReference("https://cdn.example.test/photo.jpg", "image"),
                Path(directory),
            )
            self.assertTrue(result.path.is_file())
            self.assertEqual(result.path.read_bytes(), b"jpegdata")
            self.assertFalse(list(Path(directory).glob("*.part")))

    def test_resolver_enforces_aggregate_remote_download_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = AssetDownloader(
                session=FakeDownloadSession(),
                max_bytes=12,
                url_validator=lambda url: None,
            )
            resolver = AssetResolver(downloader)

            with self.assertRaisesRegex(AssetError, "Combined stock assets"):
                resolver.resolve(
                    Path(directory),
                    sources=[
                        "https://cdn.example.test/one.jpg",
                        "https://cdn.example.test/two.jpg",
                    ],
                )
            self.assertFalse(list(Path(directory).iterdir()))

    def test_ssrf_guard_rejects_loopback(self):
        with self.assertRaisesRegex(AssetError, "Private or local"):
            validate_public_url("http://127.0.0.1/private.mp4")

    def test_auto_caption_timing_covers_full_duration(self):
        cues = build_caption_cues(
            "A fast hook. Then a useful explanation that keeps moving.",
            5.0,
            words_per_caption=4,
        )
        self.assertEqual(cues[0].start, 0.0)
        self.assertEqual(cues[-1].end, 5.0)
        self.assertTrue(all(cue.end > cue.start for cue in cues))

    def test_pipeline_rejects_non_vertical_dimensions(self):
        with self.assertRaisesRegex(ValueError, "9:16"):
            VerticalVideoPipeline(frame_size=(640, 640))


@skipUnless(importlib.util.find_spec("moviepy"), "MoviePy is not installed")
class LightweightRenderTests(TestCase):
    def test_renders_short_silent_vertical_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "background.jpg"
            Image.new("RGB", (640, 360), (35, 50, 95)).save(image_path)
            output_path = root / "result.mp4"
            pipeline = VerticalVideoPipeline(
                frame_size=(180, 320),
                fps=5,
                ffmpeg_threads=1,
                preset="ultrafast",
                asset_resolver=AssetResolver(),
            )

            result = pipeline.render(
                script="A concise subtitle test.",
                output_path=output_path,
                asset_sources=[image_path],
                duration=0.8,
                caption_style=CaptionStyle(font_size=20, stroke_width=1),
            )

            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)
            self.assertEqual(result.width, 180)
            self.assertEqual(result.height, 320)
