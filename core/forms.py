from django import forms
from django.conf import settings

from .constants import BRIEF_KEYS, BRIEF_LABELS, BRIEF_MAX_LENGTH


class ChatMessageForm(forms.Form):
    client_id = forms.CharField(required=False, max_length=64)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        limit = settings.MESSAGE_MAX_LENGTH
        # فیلد در زمان ساخت فرم ساخته می‌شود تا override_settings در تست‌ها
        # و تغییر متغیر محیطی بدون بارگذاری دوبارهٔ ماژول اثر کند.
        self.fields["text"] = forms.CharField(
            label="پیام",
            max_length=limit,
            strip=True,
            error_messages={
                "required": "متن پیام خالی است.",
                "max_length": f"پیام نباید بیشتر از {limit} نویسه باشد.",
            },
        )


class BriefForm(forms.Form):
    """فرم ویرایش بریف. خالی‌گذاشتن یک فیلد آن را «تکمیل‌نشده» می‌کند."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key in BRIEF_KEYS:
            self.fields[key] = forms.CharField(
                label=BRIEF_LABELS[key],
                required=False,
                max_length=BRIEF_MAX_LENGTH,
                strip=True,
                widget=forms.Textarea(
                    attrs={
                        "rows": 2,
                        "class": "brief-input",
                        "placeholder": f"{BRIEF_LABELS[key]} را بنویس...",
                    }
                ),
                error_messages={
                    "max_length": f"{BRIEF_LABELS[key]} نباید بیشتر از {BRIEF_MAX_LENGTH} نویسه باشد.",
                },
            )

    def cleaned_brief(self) -> dict:
        return {
            key: (self.cleaned_data.get(key) or "").strip()
            for key in BRIEF_KEYS
            if (self.cleaned_data.get(key) or "").strip()
        }
