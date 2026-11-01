"""ورود و به‌روزرسانی جزوه‌های PDF در SQLite.

نمونهٔ اجرا:
    python manage.py import_handouts
    python manage.py import_handouts "C:\\Users\\iman\\Documents\\جزوه ها"
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from knowledge.models import Chunk, Document, Page
from knowledge.pdf import (
    PdfExtractionError,
    chunk_text,
    extract_pdf,
    hash_file,
    make_search_text,
)


class Command(BaseCommand):
    help = "خواندن PDFهای یک پوشه و ذخیرهٔ متن، نام فایل و شمارهٔ صفحه در SQLite (بدون رکورد تکراری)."

    def add_arguments(self, parser):
        parser.add_argument(
            "folder",
            nargs="?",
            default=None,
            help="مسیر پوشه‌ای که فایل‌های PDF در آن قرار دارد. اگر خالی بماند از HANDOUTS_DIR استفاده می‌شود.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="فقط بررسی و گزارش؛ هیچ تغییری در پایگاه داده انجام نمی‌شود.",
        )

    def handle(self, *args, **options):
        folder_value = options.get("folder") or settings.HANDOUTS_DIR
        if not folder_value:
            raise CommandError(
                "مسیر پوشهٔ جزوه‌ها مشخص نیست. مسیر را به دستور بده یا HANDOUTS_DIR را در .env تنظیم کن."
            )
        folder = Path(folder_value).expanduser()
        dry_run = bool(options["dry_run"])

        if not folder.exists() or not folder.is_dir():
            raise CommandError(f"پوشه پیدا نشد: {folder}")

        pdfs = sorted(
            (path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf"),
            key=lambda item: str(item).lower(),
        )
        if not pdfs:
            raise CommandError("در این پوشه هیچ فایل PDF پیدا نشد.")

        created = updated = skipped = failed = 0
        scanned: list[tuple[str, int, list[int]]] = []
        errors: list[tuple[str, str]] = []
        seen_names: set[str] = set()

        self.stdout.write(f"شروع بررسی {len(pdfs)} فایل PDF در: {folder}")
        if dry_run:
            self.stdout.write(self.style.WARNING("حالت آزمایشی: پایگاه داده تغییر نمی‌کند."))

        for path in pdfs:
            file_name = path.name
            if file_name in seen_names:
                failed += 1
                errors.append((file_name, "نام تکراری در پوشه‌های مختلف؛ برای جلوگیری از بازنویسی نادیده گرفته شد."))
                continue
            seen_names.add(file_name)

            try:
                file_hash = hash_file(path)
                file_size = path.stat().st_size
                existing = Document.objects.filter(file_name=file_name).first()

                if existing and existing.file_hash == file_hash:
                    if existing.source_path != str(path.resolve()):
                        if not dry_run:
                            existing.source_path = str(path.resolve())
                            existing.save(update_fields=["source_path", "updated_at"])
                    skipped += 1
                    self.stdout.write(f"  = بدون تغییر: {file_name}")
                    continue

                extraction = extract_pdf(path)

                if extraction.scanned_pages:
                    scanned.append((file_name, extraction.page_count, extraction.scanned_pages))

                if dry_run:
                    action = "به‌روزرسانی" if existing else "ورود"
                    self.stdout.write(
                        f"  ? {action}: {file_name} — {extraction.page_count} صفحه، "
                        f"{extraction.text_page_count} صفحهٔ دارای متن"
                    )
                    continue

                with transaction.atomic():
                    if existing:
                        existing.pages.all().delete()
                        document = existing
                        document.file_hash = file_hash
                        document.file_size = file_size
                        document.source_path = str(path.resolve())
                    else:
                        document = Document(
                            file_name=file_name,
                            file_hash=file_hash,
                            file_size=file_size,
                            source_path=str(path.resolve()),
                        )
                        document.save()

                    chunk_order = 0
                    text_pages = 0
                    for page_data in extraction.pages:
                        page_obj = Page.objects.create(
                            document=document,
                            number=page_data.number,
                            text=page_data.text,
                            char_count=page_data.char_count,
                        )
                        if page_data.char_count >= 20:
                            text_pages += 1
                        for piece in chunk_text(page_data.text):
                            chunk_order += 1
                            Chunk.objects.create(
                                document=document,
                                page=page_obj,
                                order=chunk_order,
                                text=piece,
                                search_text=make_search_text(piece),
                                char_count=len(piece),
                            )

                    document.page_count = extraction.page_count
                    document.text_page_count = text_pages
                    document.chunk_count = chunk_order
                    document.is_scanned = extraction.is_scanned
                    document.scanned_pages = extraction.scanned_pages
                    document.save(
                        update_fields=[
                            "file_hash",
                            "file_size",
                            "source_path",
                            "page_count",
                            "text_page_count",
                            "chunk_count",
                            "is_scanned",
                            "scanned_pages",
                            "updated_at",
                        ]
                    )

                if existing:
                    updated += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ↻ به‌روزرسانی: {file_name} — {extraction.page_count} صفحه، {chunk_order} بخش"
                        )
                    )
                else:
                    created += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  + ورود: {file_name} — {extraction.page_count} صفحه، {chunk_order} بخش"
                        )
                    )

            except PdfExtractionError as exc:
                failed += 1
                errors.append((file_name, str(exc)))
                self.stdout.write(self.style.ERROR(f"  ! خطا: {file_name} — {exc}"))
            except Exception as exc:  # noqa: BLE001 - هر فایل خراب نباید کل ورود را متوقف کند
                failed += 1
                errors.append((file_name, f"خطای پیش‌بینی‌نشده ({type(exc).__name__})"))
                self.stdout.write(self.style.ERROR(f"  ! خطا: {file_name} — {type(exc).__name__}"))

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"پایان: {created} ورود جدید، {updated} به‌روزرسانی، {skipped} بدون تغییر، {failed} خطا."
            )
        )

        if scanned:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("گزارش صفحات/فایل‌های بدون متن (محتوای آن‌ها حدس زده نشد):"))
            for file_name, page_count, pages in scanned:
                sample = "، ".join(str(number) for number in pages[:20])
                suffix = " …" if len(pages) > 20 else ""
                self.stdout.write(
                    f"  - {file_name}: {len(pages)} از {page_count} صفحه بدون متن ({sample}{suffix})"
                )

        if errors:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("فایل‌های ناموفق:"))
            for file_name, reason in errors:
                self.stdout.write(f"  - {file_name}: {reason}")

        if not dry_run:
            total_pages = Document.objects.aggregate(total=Sum("page_count"))["total"] or 0
            total_chunks = Chunk.objects.count()
            self.stdout.write(
                f"ایندکس فعلی: {Document.objects.count()} جزوه، {total_pages} صفحه، {total_chunks} بخش قابل جستجو."
            )
