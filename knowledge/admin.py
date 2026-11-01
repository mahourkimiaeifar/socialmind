from django.contrib import admin

from .models import Document, Page


class PageInline(admin.TabularInline):
    model = Page
    extra = 0
    can_delete = False
    fields = ("number", "char_count", "has_text")
    readonly_fields = ("number", "char_count", "has_text")
    ordering = ("number",)

    @admin.display(description="وضعیت متن")
    def has_text(self, obj):
        if obj and obj.char_count:
            return "دارد"
        return "بدون متن"


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "file_name",
        "page_count",
        "text_page_count",
        "chunk_count",
        "is_scanned",
        "updated_at",
    )
    list_filter = ("is_scanned", "updated_at")
    search_fields = ("file_name",)
    ordering = ("file_name",)
    readonly_fields = (
        "file_name",
        "source_path",
        "file_hash",
        "file_size",
        "page_count",
        "text_page_count",
        "chunk_count",
        "is_scanned",
        "scanned_pages",
        "imported_at",
        "updated_at",
    )
    fieldsets = (
        ("شناسه و وضعیت", {
            "fields": ("file_name", "file_hash", "file_size", "imported_at", "updated_at"),
        }),
        ("آمار ایندکس", {
            "fields": ("page_count", "text_page_count", "chunk_count", "is_scanned", "scanned_pages"),
        }),
        ("مسیر خصوصی", {
            "fields": ("source_path",),
            "classes": ("collapse",),
            "description": "این مسیر فقط برای مدیر نمایش داده می‌شود و در سایت عمومی نیست.",
        }),
    )
    inlines = [PageInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("pages")
