from django.conf import settings
from django.db.models import Sum

from knowledge.models import Document


def site_context(request):
    """اطلاعات عمومی و بدون دادهٔ حساس برای همهٔ قالب‌ها."""
    document_count = Document.objects.count()
    page_count = Document.objects.aggregate(total=Sum("page_count"))["total"] or 0
    return {
        "site_name": "Socia Mind",
        "documents_count": document_count,
        "handout_pages_count": page_count,
        "current_session_note": "گفتگوها به همین نشست مرورگر محدود هستند.",
        "app_version": "1.0",
        "is_debug": settings.DEBUG,
    }
