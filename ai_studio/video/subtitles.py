"""Caption timing and Pillow-based bitmap rendering without ImageMagick."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True, slots=True)
class CaptionCue:
    text: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Caption text cannot be empty.")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Caption cues require 0 <= start < end.")


@dataclass(frozen=True, slots=True)
class CaptionStyle:
    font_path: str | None = None
    font_size: int = 66
    text_color: tuple[int, int, int, int] = (255, 255, 255, 255)
    highlight_color: tuple[int, int, int, int] = (128, 255, 82, 255)
    background_color: tuple[int, int, int, int] = (5, 8, 18, 205)
    stroke_color: tuple[int, int, int, int] = (0, 0, 0, 255)
    stroke_width: int = 3
    horizontal_margin_ratio: float = 0.08
    vertical_position_ratio: float = 0.72
    padding_x: int = 38
    padding_y: int = 24
    corner_radius: int = 24
    line_spacing: int = 10

    def __post_init__(self) -> None:
        if self.font_size < 12:
            raise ValueError("Caption font size must be at least 12 pixels.")
        if not 0.02 <= self.horizontal_margin_ratio <= 0.4:
            raise ValueError("Caption horizontal margin ratio is invalid.")
        if not 0 <= self.vertical_position_ratio <= 1:
            raise ValueError("Caption vertical position ratio is invalid.")


@dataclass(frozen=True, slots=True)
class CaptionBitmap:
    pixels: np.ndarray
    position: tuple[int, int]


def build_caption_cues(
    script: str,
    duration: float,
    *,
    words_per_caption: int = 6,
    min_duration: float = 0.55,
) -> list[CaptionCue]:
    """Build readable, word-weighted cues when speech timings are unavailable."""

    if duration <= 0:
        raise ValueError("Caption duration must be positive.")
    if words_per_caption < 1:
        raise ValueError("words_per_caption must be positive.")
    words = re.findall(r"\S+", " ".join(script.split()))
    if not words:
        return []

    max_cues = max(1, int(duration / min_duration))
    adjusted_size = max(words_per_caption, math.ceil(len(words) / max_cues))
    chunks: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        sentence_end = bool(re.search(r"[.!?…][\"')\]]?$", word))
        if len(current) >= adjusted_size or (
            sentence_end and len(current) >= max(3, adjusted_size - 2)
        ):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)

    weights = [
        max(1.0, len(chunk) + 0.35 * sum(word.endswith((".", "!", "?")) for word in chunk))
        for chunk in chunks
    ]
    total_weight = sum(weights)
    cues: list[CaptionCue] = []
    cursor = 0.0
    for index, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
        end = duration if index == len(chunks) - 1 else cursor + duration * weight / total_weight
        cues.append(CaptionCue(" ".join(chunk), cursor, end))
        cursor = end
    return cues


def coerce_caption_cues(values: list[Any], duration: float) -> list[CaptionCue]:
    cues: list[CaptionCue] = []
    for value in values:
        if isinstance(value, CaptionCue):
            cue = value
        elif isinstance(value, dict):
            cue = CaptionCue(
                text=str(value["text"]),
                start=float(value["start"]),
                end=float(value["end"]),
            )
        elif isinstance(value, (tuple, list)) and len(value) == 3:
            cue = CaptionCue(str(value[0]), float(value[1]), float(value[2]))
        else:
            raise ValueError("Caption timings must contain CaptionCue, mapping, or triples.")
        if cue.end > duration + 0.05:
            raise ValueError("A caption cue extends beyond the video duration.")
        cues.append(cue)
    cues.sort(key=lambda cue: cue.start)
    for previous, current in zip(cues, cues[1:]):
        if current.start < previous.end:
            raise ValueError("Caption cues cannot overlap.")
    return cues


class CaptionBitmapRenderer:
    def __init__(self, style: CaptionStyle | None = None) -> None:
        self.style = style or CaptionStyle()

    def render(self, text: str, frame_size: tuple[int, int]) -> CaptionBitmap:
        frame_width, frame_height = frame_size
        max_text_width = int(frame_width * (1 - 2 * self.style.horizontal_margin_ratio))
        font = self._load_font()
        lines = self._wrap(text, font, max_text_width - 2 * self.style.padding_x)
        probe = Image.new("RGBA", (max_text_width, frame_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        line_boxes = [
            draw.textbbox(
                (0, 0),
                line,
                font=font,
                stroke_width=self.style.stroke_width,
            )
            for line in lines
        ]
        text_width = max(box[2] - box[0] for box in line_boxes)
        text_height = sum(box[3] - box[1] for box in line_boxes)
        text_height += self.style.line_spacing * max(0, len(lines) - 1)
        bitmap_width = min(max_text_width, text_width + 2 * self.style.padding_x)
        bitmap_height = text_height + 2 * self.style.padding_y
        image = Image.new("RGBA", (bitmap_width, bitmap_height), (0, 0, 0, 0))
        canvas = ImageDraw.Draw(image)
        canvas.rounded_rectangle(
            (0, 0, bitmap_width - 1, bitmap_height - 1),
            radius=min(self.style.corner_radius, bitmap_height // 2),
            fill=self.style.background_color,
        )
        y = self.style.padding_y
        for line, box in zip(lines, line_boxes, strict=True):
            line_width = box[2] - box[0]
            line_height = box[3] - box[1]
            x = (bitmap_width - line_width) // 2
            canvas.text(
                (x, y - box[1]),
                line,
                font=font,
                fill=self.style.text_color,
                stroke_width=self.style.stroke_width,
                stroke_fill=self.style.stroke_color,
            )
            y += line_height + self.style.line_spacing
        x_position = (frame_width - bitmap_width) // 2
        center_y = int(frame_height * self.style.vertical_position_ratio)
        y_position = max(0, min(frame_height - bitmap_height, center_y - bitmap_height // 2))
        return CaptionBitmap(np.asarray(image), (x_position, y_position))

    def _load_font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            self.style.font_path,
            "DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return ImageFont.truetype(str(Path(candidate)), self.style.font_size)
            except OSError:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _wrap(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
        if max_width < 40:
            raise ValueError("Caption frame is too narrow.")
        probe = Image.new("RGB", (max_width, 100), "black")
        draw = ImageDraw.Draw(probe)
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            width = draw.textbbox((0, 0), candidate, font=font)[2]
            if width <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [text]

