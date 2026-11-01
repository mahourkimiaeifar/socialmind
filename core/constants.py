"""ثابت‌های مشترک بریف و وضعیت گفتگو."""

BRIEF_FIELDS = (
    {"key": "domain_product", "label": "حوزه و محصول/خدمت"},
    {"key": "audience", "label": "مخاطب اصلی"},
    {"key": "concern", "label": "دغدغهٔ جزئی مخاطب"},
    {"key": "message", "label": "پیام تک‌موضوعی"},
    {"key": "goal", "label": "هدف محتوا"},
    {"key": "capabilities", "label": "امکانات اجرا"},
    {"key": "tone", "label": "لحن"},
    {"key": "duration", "label": "مدت"},
    {"key": "expected_action", "label": "اقدام مورد انتظار"},
)

BRIEF_KEYS = tuple(item["key"] for item in BRIEF_FIELDS)
BRIEF_LABELS = {item["key"]: item["label"] for item in BRIEF_FIELDS}
BRIEF_MAX_LENGTH = 800

STATUS_COLLECTING = "collecting"
STATUS_BRIEF_READY = "brief_ready"
STATUS_GENERATING = "generating"
STATUS_GENERATED = "generated"

STATUS_CHOICES = (
    (STATUS_COLLECTING, "در حال گفتگو"),
    (STATUS_BRIEF_READY, "آمادهٔ تأیید"),
    (STATUS_GENERATING, "در حال ساخت"),
    (STATUS_GENERATED, "سناریو آماده"),
)

STATUS_LABELS = dict(STATUS_CHOICES)
