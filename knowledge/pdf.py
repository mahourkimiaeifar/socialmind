"""استخراج متن و آماده‌سازی بخش‌ها از فایل‌های PDF."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from .services import normalize_text

SPACES = re.compile(r"[ \t]+")
MANY_NEWLINES = re.compile(r"\n{3,}")
SENTENCE_END = re.compile(r"(?<=[.!?؟!؟।])\s+|\n+")


class PdfExtractionError(Exception):
    """خطای قابل نمایش هنگام خواندن PDF (بدون افشای متن)."""


@dataclass
class PageText:
    number: int
    text: str
    char_count: int = 0

    def __post_init__(self):
        if not self.char_count:
            self.char_count = len(self.text.strip())


@dataclass
class PdfExtraction:
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    total_chars: int = 0
    scanned_pages: list[int] = field(default_factory=list)
    text_page_count: int = 0
    is_scanned: bool = False


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = SPACES.sub(" ", text)
    text = MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pdf(path: Path) -> PdfExtraction:
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - خطای کتابخانه باید به پیام فارسی تبدیل شود
        raise PdfExtractionError(f"خواندن فایل ممکن نشد ({type(exc).__name__})") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise PdfExtractionError("فایل PDF رمزگذاری شده است و قابل خواندن نیست.") from exc

    pages: list[PageText] = []
    total_chars = 0
    scanned_pages: list[int] = []

    for index, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        text = clean_text(raw)
        char_count = len(text)
        total_chars += char_count
        if char_count < 20:
            scanned_pages.append(index)
        pages.append(PageText(number=index, text=text, char_count=char_count))

    page_count = len(pages)
    text_page_count = page_count - len(scanned_pages)
    is_scanned = total_chars < 100 or (page_count > 0 and text_page_count == 0)

    return PdfExtraction(
        page_count=page_count,
        pages=pages,
        total_chars=total_chars,
        scanned_pages=scanned_pages,
        text_page_count=text_page_count,
        is_scanned=is_scanned,
    )


def chunk_text(text: str, size: int = 1100, overlap: int = 140) -> list[str]:
    """تقسیم متن به بخش‌های هم‌پوشان با سعی در شکستن روی مرز جمله."""
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            window_start = start + int(size * 0.55)
            best = -1
            for match in SENTENCE_END.finditer(text[window_start:end]):
                best = window_start + match.end()
            if best > start:
                end = best
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def make_search_text(text: str) -> str:
    return normalize_text(text)
