"""اتصال سمت سرور به مدل زبانی.

کلید فقط از تنظیمات Django (که آن را از متغیر محیطی می‌خواند) استفاده می‌شود.
هیچ‌گاه در قالب، پاسخ HTTP یا لاگ چاپ نمی‌شود.
"""
from __future__ import annotations

import json
import logging
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("core.services.llm")


def _build_ssl_context() -> ssl.SSLContext:
    """ساخت بافت TLS سازگار با شبکه‌های سخت‌گیر.

    OpenSSL 3.5 به‌طور پیش‌فرض گروه ترکیبی پساکوانتومی
    ``X25519MLKEM768`` را پیشنهاد می‌کند. برخی فایروال‌ها/پروکسی‌ها
    این دست‌دادن (handshake) را قطع می‌کنند. محدودکردن گروه به
    ``X25519`` بدون کاهش امنیت معمول، اتصال را پایدار می‌کند.
    """
    context = ssl.create_default_context()
    try:
        context.set_ecdh_curve("X25519")
    except (ValueError, OSError):
        # اگر نسخهٔ OpenSSL این گروه را نداشت، از پیش‌فرض استفاده می‌شود.
        pass
    return context


_SSL_CONTEXT = _build_ssl_context()


class LLMError(Exception):
    """خطای مدل با پیام فارسی قابل نمایش به کاربر."""

    def __init__(self, code: str, user_message: str):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


def _error_for_status(status: int) -> LLMError:
    if status in (401, 403):
        return LLMError(
            "invalid_key",
            "کلید API نامعتبر است یا دسترسی ندارد. مقدار OPENAI_API_KEY را در فایل .env بررسی کنید.",
        )
    if status == 404:
        return LLMError(
            "bad_endpoint",
            "نشانی سرویس مدل پیدا نشد. مقدار OPENAI_BASE_URL و OPENAI_API_STYLE را بررسی کنید.",
        )
    if status == 429:
        return LLMError(
            "rate_limited",
            "سرویس مدل موقتاً شلوغ است. چند لحظه بعد دوباره تلاش کنید.",
        )
    if status == 400:
        return LLMError(
            "bad_request",
            "درخواست به سرویس مدل پذیرفته نشد. نام مدل یا تنظیمات OPENAI_MODEL را بررسی کنید.",
        )
    if status >= 500:
        return LLMError(
            "server_error",
            "سرویس مدل پاسخ نداد. چند لحظه بعد دوباره تلاش کنید.",
        )
    return LLMError(
        "http_error",
        "سرویس مدل پاسخ معتبری برنگرداند. تنظیمات اتصال را بررسی کنید.",
    )


def _post_json(url: str, payload: dict, headers: dict, timeout: int):
    """ارسال JSON به سرویس. این تابع در تست‌ها mock می‌شود."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
            raw = response.read()
    except HTTPError as exc:
        logger.warning("LLM HTTP error status=%s", exc.code)
        raise _error_for_status(exc.code) from exc
    except (TimeoutError, socket.timeout) as exc:
        logger.warning("LLM timeout")
        raise LLMError(
            "timeout",
            "پاسخی از سرویس مدل دریافت نشد. اتصال شبکه را بررسی کنید و دوباره تلاش کنید.",
        ) from exc
    except URLError as exc:
        logger.warning("LLM network error")
        raise LLMError(
            "network",
            "ارتباط با سرویس مدل برقرار نشد. اتصال شبکه یا دسترسی سرور را بررسی کنید.",
        ) from exc
    except OSError as exc:
        # قطع ناگهانی اتصال (مثل RemoteDisconnected یا ConnectionResetError)
        # نیز باید پیام روشن شبکه بدهد، نه خطای مبهم.
        logger.warning("LLM connection dropped: %s", type(exc).__name__)
        raise LLMError(
            "network",
            "ارتباط با سرویس مدل برقرار نشد. اتصال شبکه یا دسترسی سرور را بررسی کنید.",
        ) from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("LLM returned invalid JSON")
        raise LLMError(
            "invalid_json",
            "پاسخ سرویس مدل قابل خواندن نبود. دوباره تلاش کنید.",
        ) from exc


def extract_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") in {"output_text", "text"} and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        if parts:
            return "\n".join(parts).strip()

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            if parts:
                return "\n".join(parts).strip()
    return ""


REQUIRED_SECTION_MARKERS = (
    ("ایده", ("ایده", "پیام اصلی")),
    ("دغدغه", ("دغدغه", "مشکل مخاطب")),
    ("تکنیک", ("تکنیک", "روش", "ساختار")),
    ("قلاب", ("قلاب", "هوک")),
    ("صحنه", ("صحنه", "سکانس")),
    ("اقدام", ("دعوت به اقدام", "CTA", "فراخوان")),
)


def validate_scenario(text: str) -> None:
    if not text or len(text.strip()) < 200:
        raise LLMError(
            "empty_response",
            "پاسخ مدل خیلی کوتاه یا خالی بود؛ سناریویی ثبت نشد. دوباره تلاش کنید.",
        )
    missing = [label for label, markers in REQUIRED_SECTION_MARKERS if not any(marker in text for marker in markers)]
    if missing:
        raise LLMError(
            "bad_format",
            "پاسخ مدل بخش‌های لازم سناریو را نداشت؛ خروجی ثبت نشد. دوباره تلاش کنید.",
        )


def generate_scenario(brief: dict, source_texts: list[str]) -> str:
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise LLMError(
            "missing_key",
            "کلید API روی سرور تنظیم نشده است. مقدار OPENAI_API_KEY را در فایل .env قرار دهید و سرور را دوباره اجرا کنید.",
        )
    if not source_texts:
        raise LLMError(
            "no_sources",
            "برای انتخاب روش، مدرک کافی در جزوه‌ها پیدا نشد. یک جزئیات بیشتر به بریف اضافه کنید یا سؤال تکمیلی را پاسخ دهید.",
        )

    user_prompt = build_user_prompt(brief, source_texts)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SociaMind/1.0",
    }

    if settings.OPENAI_API_STYLE == "chat":
        url = f"{settings.OPENAI_BASE_URL}/chat/completions"
        payload = {
            "model": settings.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 2200,
        }
    else:
        url = f"{settings.OPENAI_BASE_URL}/responses"
        payload = {
            "model": settings.OPENAI_MODEL,
            "instructions": SYSTEM_PROMPT,
            "input": user_prompt,
            "max_output_tokens": 2200,
        }

    data = _post_json(url, payload, headers, settings.OPENAI_TIMEOUT)
    text = extract_text(data)
    validate_scenario(text)
    return text
