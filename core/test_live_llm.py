r"""تست‌های زندهٔ مدل زبانی.

این فایل به‌صورت پیش‌فرض اجرا نمی‌شود، چون به شبکه و کلید واقعی نیاز دارد.
اجرای جداگانه در PowerShell:

    $env:RUN_LIVE_LLM_TESTS="1"
    .\.venv\Scripts\python.exe manage.py test core.test_live_llm -v 2

اگر کلید تنظیم نشده باشد یا شبکه در دسترس نباشد، تست با پیام روشن رد می‌شود
و هیچ خروجی ساختگی جای آن نمی‌نشیند.
"""
from __future__ import annotations

import os
from unittest import SkipTest

from django.conf import settings
from django.test import TestCase, override_settings

from .services.llm import generate_scenario

LIVE_ENABLED = os.environ.get("RUN_LIVE_LLM_TESTS") == "1"


@override_settings(OPENAI_TIMEOUT=120)
class LiveScenarioGenerationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not LIVE_ENABLED:
            raise SkipTest("RUN_LIVE_LLM_TESTS=1 تنظیم نشده است.")
        if not settings.OPENAI_API_KEY:
            raise SkipTest("OPENAI_API_KEY روی سرور تنظیم نشده است.")

    def test_live_model_returns_a_complete_persian_scenario(self):
        brief = {
            "domain_product": "آموزش زبان انگلیسی برای بزرگسالان شاغل",
            "audience": "والدین شاغلی که وقت کافی برای تمرین ندارند",
            "concern": "بعد از دو روز تمرین را رها می‌کنند و فکر می‌کنند اراده ندارند",
            "message": "با ده دقیقه در روز هم می‌شود شروع کرد",
            "goal": "مخاطب یک قدم کوچک را امتحان کند",
            "capabilities": "فقط موبایل و نور طبیعی",
            "tone": "صمیمی و ساده",
            "duration": "۶۰ ثانیه",
            "expected_action": "در کامنت بنویسد بزرگ‌ترین مانع شروعش چیست",
        }
        sources = [
            "قلاب باید دغدغهٔ واقعی مخاطب را در چند ثانیهٔ اول نشان دهد. "
            "صحنه‌ها کوتاه باشند و هر صحنه یک پیام روشن داشته باشد. "
            "دعوت به اقدام باید یک کار مشخص و ساده باشد."
        ]
        text = generate_scenario(brief, sources)
        self.assertGreater(len(text), 200)
        for marker in ("ایده", "دغدغه", "تکنیک", "قلاب", "صحنه", "دعوت به اقدام"):
            self.assertIn(marker, text)
        self.assertNotIn("جزوه-", text)
