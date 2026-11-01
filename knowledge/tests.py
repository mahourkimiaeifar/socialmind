from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from knowledge.models import Chunk, Document, Page
from knowledge.pdf import (
    PageText,
    PdfExtraction,
    chunk_text,
    extract_pdf,
    make_search_text,
)
from knowledge.services import build_query_from_brief, normalize_text, search_chunks, tokenize


class NormalizationTests(TestCase):
    def test_arabic_letters_and_digits_are_normalized(self):
        self.assertEqual(normalize_text("كتاب ۱۲۳ ي"), "کتاب 123 ی")

    def test_zero_width_non_joiner_becomes_space(self):
        self.assertEqual(normalize_text("می‌خواهم"), "می خواهم")

    def test_stop_words_are_removed_from_tokens(self):
        terms = tokenize("این یک پیام برای مخاطب است و از قلاب می‌گوید")
        self.assertIn("پیام", terms)
        self.assertIn("مخاطب", terms)
        self.assertIn("قلاب", terms)
        self.assertNotIn("این", terms)
        self.assertNotIn("برای", terms)

    def test_query_contains_business_and_method_terms(self):
        query = build_query_from_brief(
            {
                "domain_product": "آموزش زبان",
                "audience": "والدین شاغل",
                "concern": "کمبود وقت",
            }
        )
        self.assertIn("آموزش زبان", query)
        self.assertIn("قلاب", query)


class ChunkingTests(TestCase):
    def test_short_text_stays_one_chunk(self):
        self.assertEqual(chunk_text("یک متن کوتاه برای آزمون."), ["یک متن کوتاه برای آزمون."])

    def test_long_text_is_split_with_overlap_and_limits(self):
        text = " ".join(f"جمله شماره {index} دربارهٔ سناریو و مخاطب." for index in range(1, 120))
        pieces = chunk_text(text, size=260, overlap=40)
        self.assertGreater(len(pieces), 2)
        self.assertTrue(all(len(piece) <= 300 for piece in pieces))
        self.assertTrue(all(piece.strip() for piece in pieces))

    def test_blank_text_returns_no_chunks(self):
        self.assertEqual(chunk_text("   \n\n  "), [])


class BlankPdfTests(TestCase):
    def test_blank_pdf_is_detected_as_scanned_without_guessing_text(self):
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with path.open("wb") as stream:
                writer.write(stream)

            extraction = extract_pdf(path)

        self.assertEqual(extraction.page_count, 1)
        self.assertTrue(extraction.is_scanned)
        self.assertEqual(extraction.scanned_pages, [1])
        self.assertEqual(extraction.pages[0].text, "")


class SearchTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(
            file_name="روش-سناریو.pdf",
            source_path="private/روش-سناریو.pdf",
            file_hash="a" * 64,
            file_size=1024,
            page_count=2,
            text_page_count=2,
        )
        self.page_one = Page.objects.create(
            document=self.document,
            number=1,
            text="قلاب باید دغدغهٔ واقعی مخاطب را در سه ثانیهٔ اول نشان دهد.",
            char_count=60,
        )
        self.page_two = Page.objects.create(
            document=self.document,
            number=2,
            text="قیمت و جزئیات ارسال برای فروشگاه لباس اهمیت دارد.",
            char_count=45,
        )
        for order, (page, text) in enumerate(
            (
                (self.page_one, self.page_one.text),
                (self.page_two, self.page_two.text),
            ),
            start=1,
        ):
            Chunk.objects.create(
                document=self.document,
                page=page,
                order=order,
                text=text,
                search_text=make_search_text(text),
                char_count=len(text),
            )

    def test_search_finds_relevant_page_and_returns_page_metadata(self):
        hits = search_chunks("قلاب مخاطب", limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.page.number, 1)
        self.assertEqual(hits[0].chunk.document.file_name, "روش-سناریو.pdf")
        self.assertGreater(hits[0].score, 0)

    def test_search_with_only_stop_words_returns_nothing(self):
        self.assertEqual(search_chunks("از به با در"), [])

    def test_search_does_not_invent_results_for_unrelated_term(self):
        self.assertEqual(search_chunks("کیهان‌شناسی کوانتومی"), [])


class ImportCommandTests(TestCase):
    def _extraction(self, text: str) -> PdfExtraction:
        pages = [PageText(number=1, text=text)]
        return PdfExtraction(
            page_count=1,
            pages=pages,
            total_chars=len(text),
            scanned_pages=[],
            text_page_count=1,
            is_scanned=False,
        )

    def test_import_is_idempotent_and_preserves_page_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "جزوه-آزمون.pdf"
            path.write_bytes(b"first-version")

            with patch(
                "knowledge.management.commands.import_handouts.extract_pdf",
                return_value=self._extraction("متن روش اول برای سناریونویسی و مخاطب."),
            ):
                first = io.StringIO()
                call_command("import_handouts", folder, stdout=first)
                second = io.StringIO()
                call_command("import_handouts", folder, stdout=second)

        self.assertEqual(Document.objects.count(), 1)
        document = Document.objects.get()
        self.assertEqual(document.page_count, 1)
        self.assertEqual(document.text_page_count, 1)
        self.assertEqual(document.chunk_count, 1)
        self.assertEqual(Page.objects.count(), 1)
        self.assertEqual(Chunk.objects.count(), 1)
        self.assertIn("بدون تغییر", second.getvalue())

    def test_changed_file_replaces_index_without_duplicate_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "جزوه-آزمون.pdf"
            path.write_bytes(b"version-one")

            with patch(
                "knowledge.management.commands.import_handouts.extract_pdf",
                return_value=self._extraction("متن نسخهٔ اول دربارهٔ قلاب و مخاطب."),
            ):
                call_command("import_handouts", folder, stdout=io.StringIO())

            path.write_bytes(b"version-two")
            with patch(
                "knowledge.management.commands.import_handouts.extract_pdf",
                return_value=self._extraction(
                    "متن نسخهٔ دوم دربارهٔ ساختار صحنه و دعوت به اقدام که طولانی‌تر است."
                ),
            ):
                output = io.StringIO()
                call_command("import_handouts", folder, stdout=output)

        self.assertEqual(Document.objects.count(), 1)
        document = Document.objects.get()
        self.assertEqual(document.chunk_count, 1)
        self.assertEqual(Chunk.objects.count(), 1)
        self.assertIn("نسخهٔ دوم", Chunk.objects.get().text)
        self.assertIn("به‌روزرسانی", output.getvalue())

    def test_dry_run_does_not_write_to_database(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "جزوه-آزمون.pdf"
            path.write_bytes(b"dry-run")
            with patch(
                "knowledge.management.commands.import_handouts.extract_pdf",
                return_value=self._extraction("متن آزمایشی برای حالت dry run."),
            ):
                output = io.StringIO()
                call_command("import_handouts", folder, "--dry-run", stdout=output)

        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(Page.objects.count(), 0)
        self.assertIn("حالت آزمایشی", output.getvalue())

    def test_non_pdf_folder_raises_clear_error(self):
        from django.core.management.base import CommandError

        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "note.txt").write_text("not a pdf", encoding="utf-8")
            with self.assertRaisesMessage(CommandError, "هیچ فایل PDF"):
                call_command("import_handouts", folder, stdout=io.StringIO())
