"""تگ‌ها و فیلترهای کمکی قالب‌ها (بدون وابستگی بیرونی)."""
from __future__ import annotations

import re

from django import template
from django.utils import timezone
from django.utils.html import conditional_escape, escape
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9 21v-6h6v6"/>',
    "wand": '<path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/>',
    "sparkles": '<path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/><path d="M5 17l.6 1.6L7 19l-1.4.6L5 21l-.6-1.4L3 19l1.4-.4L5 17Z"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4 20-7Z"/><path d="M22 2 11 13"/>',
    "message": '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>',
    "chart": '<path d="M4 19V5M4 19h16"/><path d="m7 15 4-4 3 3 5-6"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "clapper": '<path d="m3 7 18-4 2 7-18 4z"/><path d="m5 14-2 7 18-4-2-7"/><path d="m8 6 2 5M14 4l2 5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 1 1 5.8 1c0 2-3 2-3 4"/><path d="M12 17h.01"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "check": '<path d="m20 6-11 11-5-5"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "arrow-left": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "arrow-right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "instagram": '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><path d="M17.5 6.5h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
    "external": '<path d="M15 3h6v6M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "star": '<path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 9.4l6.1-.9Z"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
}


@register.simple_tag
def icon(name: str, size: int = 18, css_class: str = ""):
    body = ICONS.get(name, ICONS["info"])
    classes = f' class="{conditional_escape(css_class)}"' if css_class else ""
    return mark_safe(
        f'<svg{classes} width="{int(size)}" height="{int(size)}" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true" focusable="false">{body}</svg>'
    )


@register.filter
def fa_num(value):
    if value is None or value == "":
        return "۰"
    try:
        if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
            text = f"{int(value):,}"
        else:
            text = str(value)
    except (TypeError, ValueError):
        text = str(value)
    return text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)


@register.filter
def jalali_date(value, style: str = "long"):
    if not value:
        return ""
    try:
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        jy, jm, jd = _gregorian_to_jalali(local.year, local.month, local.day)
    except (AttributeError, ValueError, TypeError):
        return ""
    if style == "short":
        return fa_num(f"{jy}/{jm:02d}/{jd:02d}")
    return fa_num(f"{jd} {JALALI_MONTHS[jm - 1]} {jy}")


@register.filter
def fa_time(value):
    if not value:
        return ""
    try:
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return fa_num(local.strftime("%H:%M"))
    except (AttributeError, ValueError, TypeError):
        return ""


@register.filter
def status_tone(status: str) -> str:
    return {
        "collecting": "tone-collecting",
        "brief_ready": "tone-ready",
        "generating": "tone-generating",
        "generated": "tone-generated",
    }.get(status, "tone-collecting")


@register.filter
def format_scenario(value: str):
    """تبدیل خروجی متنی مدل به HTML امن و خوانا (بدون اجازهٔ HTML خام)."""
    if not value:
        return ""
    text = escape(str(value))
    lines = text.splitlines()
    html: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph():
        if paragraph:
            html.append("<p>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue
        if line.startswith("### "):
            flush_paragraph()
            close_list()
            html.append(f"<h4>{line[4:]}</h4>")
        elif line.startswith("## "):
            flush_paragraph()
            close_list()
            html.append(f"<h3>{line[3:]}</h3>")
        elif line.startswith("# "):
            flush_paragraph()
            close_list()
            html.append(f"<h3>{line[2:]}</h3>")
        elif line.startswith("- ") or line.startswith("• "):
            flush_paragraph()
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{line[2:]}</li>")
        elif re.match(r"^\d+[.)]\s+", line):
            flush_paragraph()
            if not in_list:
                html.append('<ul class="numbered">')
                in_list = True
            item = re.sub(r"^\d+[.)]\s+", "", line)
            html.append(f"<li>{item}</li>")
        elif line.startswith("> "):
            flush_paragraph()
            close_list()
            html.append(f"<blockquote>{line[2:]}</blockquote>")
        else:
            close_list()
            paragraph.append(line)

    flush_paragraph()
    close_list()
    result = "\n".join(html)
    result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", result)
    return mark_safe(result)
