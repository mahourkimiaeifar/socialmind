"""بازیابی اصول روشی از جزوه‌ها برای هر نوبت گفتگو.

این ماژول در هر پاسخ کاربر، جزوه‌ها را جست‌وجو می‌کند و بر اساس موضوعی که
در متن بازیابی‌شده پیدا می‌شود، «نوع سؤال تکمیلی» را انتخاب می‌کند. هیچ متن
خام، نام فایل یا شمارهٔ صفحه‌ای به کاربر نشان داده نمی‌شود؛ این اطلاعات فقط
در داده‌های کمکی پیام برای مدیر ثبت می‌شوند.

نکتهٔ مهم: سؤال‌ها از کتابخانهٔ ثابت و قابل‌بازبینی انتخاب می‌شوند؛ متن جزوه
نقل نمی‌شود و ادعای جدیدی از جزوه ساخته نمی‌شود.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings

from knowledge.services import build_query_for_turn, normalize_text, search_chunks

# برای هر بخش بریف، چند «موضوع روشی» و سؤال تکمیلی متناظر داریم.
# انتخاب سؤال فقط وقتی انجام می‌شود که موضوع در متن بازیابی‌شده دیده شود.
CUE_RULES: dict[str, tuple[tuple[tuple[str, ...], str], ...]] = {
    "domain_product": (
        (
            ("محصول", "خدمت", "ارائه"),
            "دقیقاً چه محصول یا خدمتی ارائه می‌دهی و اولین فایدهٔ مشخص آن برای مخاطب چیست؟",
        ),
        (
            ("آموزش", "مشاوره"),
            "این آموزش یا مشاوره دقیقاً چه مشکلی را برای مخاطب حل می‌کند؟",
        ),
    ),
    "audience": (
        (
            ("موقعیت", "زمان", "لحظه", "روزمره"),
            "مخاطبت را در یک موقعیت واقعی روزمره تصور کن؛ دقیقاً کجا و چه زمانی این موضوع برایش مهم می‌شود؟",
        ),
        (
            ("پرسونا", "ویژگی", "نقش", "سن"),
            "مخاطبت را با دو ویژگی مشخص توصیف کن؛ مثلاً نقش شغلی و مرحلهٔ زندگی‌اش.",
        ),
    ),
    "concern": (
        (
            ("ترس", "نگرانی", "اضطراب"),
            "بزرگ‌ترین ترس یا نگرانی مخاطب در این موضوع چیست؟",
        ),
        (
            ("مانع", "بهانه", "وقت", "انرژی"),
            "چه بهانه یا مانعی باعث می‌شود مخاطب کاری را که می‌داند مفید است انجام ندهد؟",
        ),
        (
            ("لحظه", "موقعیت", "روزمره"),
            "این دغدغه دقیقاً در چه لحظه‌ای از روز یا کار مخاطب سراغش می‌آید؟",
        ),
    ),
    "message": (
        (
            ("باور", "اشتباه", "تصور"),
            "کدام باور اشتباه رایج را می‌خواهی اصلاح کنی؟",
        ),
        (
            ("فایده", "نتیجه", "تغییر"),
            "مخاطب بعد از شنیدن پیام چه فایدهٔ کوچک و قابل مشاهدهٔ مشخصی می‌گیرد؟",
        ),
    ),
    "goal": (
        (
            ("اقدام", "رفتار", "قدم"),
            "بعد از دیدن محتوا، اولین اقدام کوچک و قابل اندازه‌گیری مخاطب چه باشد؟",
        ),
        (
            ("اعتماد", "آگاهی"),
            "موفقیت این محتوا را با چه نشانهٔ ساده و قابل مشاهده می‌سنجی؟",
        ),
    ),
    "capabilities": (
        (
            ("نور", "صدا", "لوکیشن", "دوربین"),
            "در محل فیلم‌برداری نور و صدای مناسبی داری یا راه ساده‌تری مثل تصویر ثابت انتخاب کنیم؟",
        ),
        (
            ("موبایل", "زمان", "ویرایش"),
            "برای ساخت و ویرایش، چقدر زمان در دسترس داری؟",
        ),
    ),
    "expected_action": (
        (
            ("کامنت", "پیام", "ذخیره"),
            "دقیقاً چه جمله یا سؤالی را در پایان بگذاریم که پاسخ‌دادن به آن برای مخاطب راحت باشد؟",
        ),
        (
            ("سایت", "لینک", "صفحه"),
            "مخاطب بعد از دیدن محتوا دقیقاً کجا باید برود و چه چیزی آنجا می‌بیند؟",
        ),
    ),
}

# پاسخ کوتاه‌تر از این آستانه، «ناقص» در نظر گرفته می‌شود و یک سؤال تکمیلی می‌گیرد.
THIN_LENGTH = {
    "domain_product": 12,
    "audience": 10,
    "concern": 24,
    "message": 15,
    "goal": 12,
    "capabilities": 12,
    "expected_action": 12,
}

HANDOUT_PROBE_FIELDS = frozenset(THIN_LENGTH)


@dataclass(frozen=True)
class TurnGrounding:
    """نتیجهٔ جست‌وجوی جزوه‌ها در یک نوبت گفتگو."""

    hits: tuple = ()
    cue: str | None = None
    cue_key: str | None = None
    matched_terms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_hits(self) -> bool:
        return bool(self.hits)

    @property
    def summary(self) -> dict:
        """خلاصهٔ قابل ثبت برای مدیر؛ بدون متن خام جزوه."""
        sources = []
        seen = set()
        for hit in self.hits:
            key = (hit.chunk.document.file_name, hit.chunk.page.number)
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "document": key[0],
                    "page": key[1],
                    "score": hit.score,
                }
            )
        return {
            "count": len(sources),
            "sources": sources,
            "cue": self.cue_key,
            "matched": list(self.matched_terms[:5]),
            "grounded": bool(self.cue),
        }


def is_thin_answer(field: str, text: str) -> bool:
    threshold = THIN_LENGTH.get(field)
    if not threshold:
        return False
    return len(normalize_text(text)) < threshold


def retrieve_for_turn(brief: dict, latest_text: str = "", field: str | None = None) -> TurnGrounding:
    """جست‌وجوی جزوه‌ها با بریف فعلی و پاسخ تازهٔ کاربر.

    اگر بازیابی خاموش باشد یا مدرکی پیدا نشود، نتیجهٔ خالی برمی‌گردد و
    برنامه به رفتار قبلی خود برمی‌گردد؛ هیچ مدرکی از خودش ساخته نمی‌شود.
    """
    if not getattr(settings, "HANDOUT_RETRIEVAL_PER_TURN", True):
        return TurnGrounding()

    limit = int(getattr(settings, "HANDOUT_TURN_SOURCES", 5) or 5)
    query = build_query_for_turn(brief, latest_text=latest_text, field=field)
    hits = search_chunks(query, limit=limit)
    if not hits:
        return TurnGrounding()

    haystack = normalize_text(" ".join(hit.chunk.text for hit in hits))
    for keywords, question in CUE_RULES.get(field or "", ()):
        matched = tuple(word for word in keywords if word in haystack)
        if matched:
            return TurnGrounding(
                hits=tuple(hits),
                cue=question,
                cue_key=keywords[0],
                matched_terms=matched,
            )
    return TurnGrounding(hits=tuple(hits))
