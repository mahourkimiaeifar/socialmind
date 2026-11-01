"""ابزارهای نرمال‌سازی و جست‌وجوی متنی جزوه‌ها.

جست‌وجو با ORM انجام می‌شود؛ برای هر واژه، بخش‌های نامزد با contains پیدا
می‌شوند و سپس امتیازدهی ساده (فراوانی واژه + وزن نادر بودن) انجام می‌شود.
این روش برای حجم ۱۹ جزوه کافی است و به پایگاه‌دادهٔ برداری نیاز ندارد.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

from django.db.models import Q

from .models import Chunk

ARABIC_TO_PERSIAN = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "ٱ": "ا",
    }
)
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
NON_WORD = re.compile(r"[^\w\u200c]+", re.UNICODE)
SPACES = re.compile(r"\s+")

STOP_WORDS = {
    "از", "به", "با", "در", "برای", "که", "این", "آن", "را", "و", "یا", "یک",
    "روی", "تا", "می", "شود", "کن", "چه", "چی", "است", "هست", "بود", "شد",
    "کرد", "کند", "شده", "های", "هایی", "هم", "اما", "اگر", "پس", "نیز",
    "بر", "بی", "نه", "خود", "ما", "شما", "او", "آنها", "ایشان", "من", "تو",
    "کردن", "بودن", "داشتن", "می‌شود", "می‌کند", "می‌توان", "باید", "شاید",
}


def normalize_text(value: str) -> str:
    """نرمال‌سازی فارسی برای مقایسه و جست‌وجو."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    value = value.translate(PERSIAN_DIGITS).translate(ARABIC_TO_PERSIAN)
    value = value.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    value = DIACRITICS.sub("", value)
    value = value.replace("ـ", "")
    value = NON_WORD.sub(" ", value)
    value = SPACES.sub(" ", value).strip().lower()
    return value


def tokenize(value: str) -> list[str]:
    terms = []
    seen = set()
    for term in normalize_text(value).split():
        if len(term) < 2 or term in STOP_WORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


METHOD_TERMS = "مصاحبه مخاطب دغدغه سناریو محتوا قلاب روایت پیام داستان صحنه"

FIELD_METHOD_TERMS = {
    "domain_product": "محصول خدمت ارائه ارزش پیشنهاد",
    "audience": "مخاطب پرسونا ویژگی موقعیت روزمره",
    "concern": "دغدغه مشکل ترس نگرانی مانع بهانه",
    "message": "پیام باور اشتباه فایده نتیجه",
    "goal": "هدف اقدام رفتار قدم اعتماد",
    "capabilities": "امکانات دوربین موبایل نور صدا لوکیشن",
    "tone": "لحن صمیمی حرفه‌ای داستانی",
    "duration": "مدت زمان کوتاه",
    "expected_action": "دعوت به اقدام کامنت پیام ذخیره لینک",
}


def build_query_from_brief(brief: dict) -> str:
    business = " ".join(
        str(brief.get(key, "") or "")
        for key in ("domain_product", "audience", "concern", "message", "goal", "expected_action")
    )
    # واژه‌های روشی هم اضافه می‌شوند تا بازیابی حتی وقتی بریف واژهٔ تخصصی ندارد
    # بتواند اصول مصاحبه و سناریونویسی را پیدا کند.
    return f"{business} {METHOD_TERMS}".strip()


def build_query_for_turn(brief: dict, latest_text: str = "", field: str | None = None) -> str:
    """ساخت پرس‌وجوی هر نوبت از بریف فعلی، پاسخ تازه و موضوع همان بخش.

    این پرس‌وجو برای انتخاب سؤال تکمیلی استفاده می‌شود، نه برای نمایش متن جزوه.
    """
    parts = [
        str(brief.get("domain_product", "") or ""),
        str(brief.get("audience", "") or ""),
        str(brief.get("concern", "") or ""),
        str(brief.get("message", "") or ""),
        str(brief.get("goal", "") or ""),
        str(latest_text or ""),
        FIELD_METHOD_TERMS.get(field or "", ""),
        METHOD_TERMS,
    ]
    return " ".join(part for part in parts if part).strip()


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


def search_chunks(query: str, limit: int = 8) -> list[SearchHit]:
    terms = tokenize(query)[:14]
    if not terms:
        return []

    candidate_q = Q()
    for term in terms:
        candidate_q |= Q(search_text__contains=term)

    candidates = list(
        Chunk.objects.select_related("document", "page")
        .filter(candidate_q)
        .exclude(text="")
        .order_by("document_id", "order")[:600]
    )
    if not candidates:
        return []

    total_chunks = max(Chunk.objects.count(), 1)
    weights: dict[str, float] = {}
    for term in terms:
        df = Chunk.objects.filter(search_text__contains=term).count()
        # واژه‌های نادرتر وزن بیشتری می‌گیرند.
        weights[term] = 1.0 + math.log((total_chunks + 1) / (df + 0.5))

    hits: list[SearchHit] = []
    for chunk in candidates:
        haystack = chunk.search_text or normalize_text(chunk.text)
        score = 0.0
        for term in terms:
            count = haystack.count(term)
            if count:
                score += min(count, 6) * weights[term]
        if score > 0:
            hits.append(SearchHit(chunk=chunk, score=round(score, 4)))

    hits.sort(key=lambda item: item.score, reverse=True)
    return hits[:limit]
