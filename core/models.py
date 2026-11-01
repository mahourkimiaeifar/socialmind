from django.conf import settings
from django.db import models

from knowledge.models import Document

from .constants import BRIEF_KEYS, BRIEF_LABELS, STATUS_CHOICES, STATUS_COLLECTING


class Conversation(models.Model):
    """یک گفتگوی سناریونویسی؛ به نشست مرورگر (و در صورت ورود، به کاربر) محدود است."""

    title = models.CharField("عنوان", max_length=140, default="گفتگوی جدید")
    session_key = models.CharField("کلید نشست", max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="کاربر",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conversations",
    )
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_COLLECTING,
        db_index=True,
    )
    brief = models.JSONField("بریف", default=dict, blank=True)
    engine_state = models.JSONField("وضعیت موتور گفتگو", default=dict, blank=True)
    brief_confirmed_at = models.DateTimeField("زمان تأیید بریف", null=True, blank=True)
    generated_at = models.DateTimeField("زمان آخرین ساخت", null=True, blank=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("زمان به‌روزرسانی", auto_now=True)

    class Meta:
        verbose_name = "گفتگو"
        verbose_name_plural = "گفتگوها"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["session_key", "-updated_at"], name="conv_session_recent_idx"),
        ]

    def __str__(self):
        return self.title or f"گفتگوی {self.pk}"

    @property
    def brief_progress(self) -> int:
        return sum(1 for key in BRIEF_KEYS if str(self.brief.get(key, "")).strip())

    @property
    def brief_total(self) -> int:
        return len(BRIEF_KEYS)

    @property
    def brief_percent(self) -> int:
        total = self.brief_total
        return round(self.brief_progress * 100 / total) if total else 0

    def brief_items(self):
        return [
            {
                "key": key,
                "label": BRIEF_LABELS[key],
                "value": str(self.brief.get(key, "")).strip(),
                "is_hypothesis": key in (self.engine_state.get("confirmed_hypotheses") or []),
            }
            for key in BRIEF_KEYS
        ]

    @property
    def message_count(self) -> int:
        return self.messages.count()

    @property
    def latest_scenario_id(self):
        message = self.messages.filter(kind=Message.KIND_SCENARIO).order_by("-created_at", "-id").first()
        return message.id if message else None


class Message(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM = "system"
    ROLE_CHOICES = (
        (ROLE_USER, "کاربر"),
        (ROLE_ASSISTANT, "دستیار"),
        (ROLE_SYSTEM, "سیستم"),
    )

    KIND_QUESTION = "question"
    KIND_NOTICE = "notice"
    KIND_BRIEF = "brief"
    KIND_SCENARIO = "scenario"
    KIND_ERROR = "error"
    KIND_FEEDBACK = "feedback"
    KIND_SYSTEM = "system"
    KIND_CHOICES = (
        (KIND_QUESTION, "پرسش"),
        (KIND_NOTICE, "اطلاع"),
        (KIND_BRIEF, "بریف"),
        (KIND_SCENARIO, "سناریو"),
        (KIND_ERROR, "خطا"),
        (KIND_FEEDBACK, "بازخورد"),
        (KIND_SYSTEM, "سیستمی"),
    )

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField("نقش", max_length=20, choices=ROLE_CHOICES)
    kind = models.CharField("نوع", max_length=20, choices=KIND_CHOICES, default=KIND_NOTICE)
    content = models.TextField("محتوا")
    meta = models.JSONField("داده‌های کمکی", default=dict, blank=True)
    client_id = models.CharField("شناسهٔ کلاینت", max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "پیام"
        verbose_name_plural = "پیام‌ها"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="msg_conv_created_idx")]

    def __str__(self):
        return f"{self.get_role_display()} — {self.content[:40]}"


class ScenarioSource(models.Model):
    """منبع روشیِ استفاده‌شده در ساخت سناریو؛ فقط برای مدیر."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="sources")
    document = models.ForeignKey(
        Document,
        verbose_name="جزوه",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scenario_sources",
    )
    document_name = models.CharField("نام فایل", max_length=255)
    page_number = models.PositiveIntegerField("شمارهٔ صفحه")
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "منبع سناریو"
        verbose_name_plural = "منابع سناریو"
        ordering = ["document_name", "page_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "document_name", "page_number"],
                name="uniq_message_source_page",
            )
        ]

    def __str__(self):
        return f"{self.document_name} — صفحهٔ {self.page_number}"
