from django.contrib import admin
from django.utils.html import format_html_join

from .constants import BRIEF_KEYS, BRIEF_LABELS, STATUS_LABELS
from .models import Conversation, Message, ScenarioSource


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    can_delete = False
    fields = ("role", "kind", "short_content", "retrieval_summary", "created_at")
    readonly_fields = ("role", "kind", "short_content", "retrieval_summary", "created_at")
    ordering = ("created_at", "id")
    verbose_name = "پیام"
    verbose_name_plural = "پیام‌های گفتگو"

    @admin.display(description="متن کوتاه")
    def short_content(self, obj):
        if not obj:
            return ""
        text = (obj.content or "").replace("\n", " ").strip()
        return text[:160] + ("…" if len(text) > 160 else "")

    @admin.display(description="منابع بررسی‌شده")
    def retrieval_summary(self, obj):
        if not obj:
            return "—"
        data = (obj.meta or {}).get("retrieval") or {}
        sources = data.get("sources") or []
        if not sources:
            return "—"
        names = "، ".join(
            f"{item.get('document', '')} ص.{item.get('page', '')}" for item in sources[:3]
        )
        extra = " …" if len(sources) > 3 else ""
        cue = " | سؤال روشی" if data.get("grounded") else ""
        return f"{len(sources)} منبع: {names}{extra}{cue}"


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status_label",
        "brief_progress",
        "message_total",
        "session_masked",
        "updated_at",
    )
    list_filter = ("status", "updated_at")
    search_fields = ("title", "session_key")
    ordering = ("-updated_at",)
    readonly_fields = (
        "title",
        "session_masked",
        "user",
        "status_label",
        "brief_display",
        "engine_state",
        "brief_confirmed_at",
        "generated_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("شناسه", {"fields": ("title", "session_masked", "user", "status_label", "created_at", "updated_at")}),
        ("بریف", {"fields": ("brief_display", "brief_confirmed_at", "generated_at")}),
        ("وضعیت داخلی موتور", {"fields": ("engine_state",), "classes": ("collapse",)}),
    )
    inlines = [MessageInline]

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("messages")

    @admin.display(description="وضعیت", ordering="status")
    def status_label(self, obj):
        return STATUS_LABELS.get(obj.status, obj.status)

    @admin.display(description="پیشرفت بریف")
    def brief_progress(self, obj):
        return f"{obj.brief_progress} از {obj.brief_total}"

    @admin.display(description="تعداد پیام")
    def message_total(self, obj):
        return obj.messages.count()

    @admin.display(description="نشست (پوشیده)")
    def session_masked(self, obj):
        key = obj.session_key or ""
        return f"{key[:8]}…" if key else "—"

    @admin.display(description="خلاصهٔ بریف")
    def brief_display(self, obj):
        rows = [
            (BRIEF_LABELS[key], str(obj.brief.get(key, "") or "").strip() or "—")
            for key in BRIEF_KEYS
        ]
        return format_html_join(
            "",
            "<div style='margin:3px 0'><strong>{}</strong>: {}</div>",
            rows,
        )


@admin.register(ScenarioSource)
class ScenarioSourceAdmin(admin.ModelAdmin):
    list_display = ("conversation_title", "document_name", "page_number", "created_at")
    search_fields = ("document_name", "message__conversation__title")
    list_filter = ("document_name",)
    ordering = ("-created_at",)
    readonly_fields = ("message", "document", "document_name", "page_number", "created_at")

    def has_add_permission(self, request):
        return False

    @admin.display(description="گفتگو")
    def conversation_title(self, obj):
        return obj.message.conversation.title if obj.message_id else "—"
