"""موتور گفتگوی بریف‌محور.

این موتور به‌صورت قطعی و قابل تست، یک سؤال در هر نوبت می‌پرسد، پاسخ را در
بریف ذخیره می‌کند و فقط وقتی همهٔ بخش‌های اصلی کامل شدند بریف را برای تأیید
نشان می‌دهد. مدل زبانی فقط در مرحلهٔ ساخت سناریو فراخوانی می‌شود.
"""
from __future__ import annotations

import re
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from core.constants import (
    BRIEF_KEYS,
    BRIEF_LABELS,
    STATUS_BRIEF_READY,
    STATUS_COLLECTING,
    STATUS_GENERATED,
    STATUS_GENERATING,
)
from core.models import Conversation, Message
from core.services.handout import (
    HANDOUT_PROBE_FIELDS,
    TurnGrounding,
    is_thin_answer,
    retrieve_for_turn,
)

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
SPACES = re.compile(r"\s+")

QUESTION_DATA = {
    "domain_product": {
        "suggestions": ["آموزش و مشاوره", "فروش محصول فیزیکی", "خدمات تخصصی", "نرم‌افزار یا اپلیکیشن"],
        "placeholder": "مثلاً: آموزش زبان انگلیسی برای بزرگسالان",
    },
    "audience": {
        "suggestions": ["مشتریان فعلی", "افراد تازه‌آشنا با برند", "متخصصان همان حوزه"],
        "placeholder": "مثلاً: والدین شاغلی که وقت کافی برای تمرین ندارند",
    },
    "concern": {
        "suggestions": [
            "نمی‌داند از کجا شروع کند",
            "وقت یا انرژی کافی ندارد",
            "به نتیجه شک دارد",
            "قبلاً تجربهٔ ناموفق داشته",
        ],
        "placeholder": "مثلاً: هر بار شروع می‌کند، بعد از دو روز رها می‌کند",
    },
    "message": {
        "suggestions": [
            "یک نکتهٔ عملی که همین امروز قابل انجام است",
            "یک باور اشتباه رایج را اصلاح کن",
            "یک تجربه یا مثال واقعی نشان بده",
        ],
        "placeholder": "مثلاً: با ده دقیقه در روز هم می‌شود شروع کرد",
    },
    "goal": {
        "suggestions": ["آموزش یک نکته", "معرفی محصول/خدمت", "افزایش اعتماد", "دریافت پیام یا کامنت"],
        "placeholder": "مثلاً: مخاطب یک قدم کوچک را امتحان کند",
    },
    "capabilities": {
        "suggestions": ["موبایل و نور طبیعی", "دوربین و لوکیشن", "تصویر ثابت/کاروسل", "انیمیشن یا متن ساده"],
        "placeholder": "مثلاً: فقط موبایل دارم و می‌توانم در محل کار فیلم بگیرم",
    },
    "tone": {
        "suggestions": ["صمیمی و ساده", "حرفه‌ای و دقیق", "داستانی", "انرژی‌بخش"],
        "placeholder": "مثلاً: دوستانه اما بدون شوخی زیاد",
    },
    "duration": {
        "suggestions": ["۳۰ ثانیه", "۶۰ ثانیه", "۹۰ ثانیه", "۳ دقیقه"],
        "placeholder": "مثلاً: حدود ۴۵ ثانیه",
    },
    "expected_action": {
        "suggestions": ["کامنت بگذارد", "پیام بدهد", "پست را ذخیره کند", "به صفحه/سایت برود"],
        "placeholder": "مثلاً: در کامنت بنویسد بزرگ‌ترین مانعش چیست",
    },
}

DONT_KNOW_MARKERS = (
    "نمیدانم",
    "نمیدونم",
    "نمی‌دانم",
    "نمی دونم",
    "نظری ندارم",
    "نظر ندارم",
    "فرقی نمی‌کند",
    "فرقی نمیکنه",
    "مطمئن نیستم",
    "بلد نیستم",
    "بلد نیستم",
    "هیچ ایده‌ای ندارم",
    "هیچ ایده ای ندارم",
)

NEGATIVE_MARKERS = {"هیچکدام", "هیچکدامش", "هیچ", "نه", "خیر", "هیچ یک"}

ORDINALS = {"اول": 1, "دوم": 2, "سوم": 3, "چهارم": 4, "پنجم": 5}


def normalize_fa(value: str) -> str:
    if not value:
        return ""
    value = str(value).replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return SPACES.sub(" ", value).strip()


def compact(value: str) -> str:
    return SPACES.sub("", normalize_fa(value)).lower()


def translate_digits(value: str) -> str:
    return (value or "").translate(PERSIAN_DIGITS)


def is_dont_know(value: str) -> bool:
    c = compact(value)
    if not c:
        return False
    return any(compact(marker) in c for marker in DONT_KNOW_MARKERS)


def is_negative(value: str) -> bool:
    c = compact(value)
    return c in {compact(item) for item in NEGATIVE_MARKERS} or c.startswith("هیچ")


def parse_choice(value: str, suggestions: Iterable[str]) -> int | None:
    """تشخیص انتخاب شماره‌ای یا متنی از میان فرضیه‌ها."""
    normalized = normalize_fa(value)
    if not normalized:
        return None
    suggestion_list = list(suggestions)
    for index, suggestion in enumerate(suggestion_list, start=1):
        if compact(suggestion) == compact(normalized):
            return index

    c = compact(normalized)
    if c in {"1", "2", "3", "4", "5"}:
        number = int(c)
        return number if 1 <= number <= len(suggestion_list) else None

    for word, number in ORDINALS.items():
        if word in normalized and number <= len(suggestion_list):
            return number

    match = re.search(r"(?:گزینه|شماره|انتخاب)?\s*([1-5])(?:\s|$|[.)،,])", translate_digits(normalized))
    if match:
        number = int(match.group(1))
        return number if 1 <= number <= len(suggestion_list) else None
    return None


def first_missing_field(brief: dict) -> str | None:
    for key in BRIEF_KEYS:
        if not str(brief.get(key, "") or "").strip():
            return key
    return None


def missing_labels(brief: dict) -> list[str]:
    return [BRIEF_LABELS[key] for key in BRIEF_KEYS if not str(brief.get(key, "") or "").strip()]


def _short(value: str, limit: int = 68) -> str:
    value = SPACES.sub(" ", normalize_fa(value))
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def question_for(field: str, brief: dict) -> str:
    domain = _short(brief.get("domain_product", ""), 55)
    audience = _short(brief.get("audience", ""), 55)
    goal = _short(brief.get("goal", ""), 50)

    if field == "domain_product":
        return "بیا از ساده‌ترین نقطه شروع کنیم: حوزهٔ کاری‌ات چیست و چه محصول یا خدمتی به مخاطب می‌دهی؟"
    if field == "audience":
        if domain:
            return f"این محتوا دقیقاً برای چه کسی ساخته می‌شود؟ مخاطب اصلی در «{domain}» چه گروهی است؟"
        return "این محتوا دقیقاً برای چه کسی ساخته می‌شود؟ مخاطب اصلی‌ات چه گروهی است؟"
    if field == "concern":
        if audience:
            return (
                f"مخاطب اصلی‌ات ({audience}) در این موضوع دقیقاً با چه دغدغه یا مشکل کوچکی "
                "درگیر است؟ هرچه جزئی‌تر بگویی، سناریو واقعی‌تر می‌شود."
            )
        return "مخاطب اصلی‌ات دقیقاً با چه دغدغه یا مشکل کوچکی درگیر است؟ هرچه جزئی‌تر، بهتر."
    if field == "message":
        return (
            "اگر مخاطب بعد از دیدن این محتوا فقط یک جمله را به یاد بسپارد، "
            "دوست داری آن جمله چه باشد؟"
        )
    if field == "goal":
        return "هدف اصلی این محتوا چیست؟ می‌خواهی مخاطب چه چیزی را بفهمد یا چه کاری بکند؟"
    if field == "capabilities":
        return (
            "برای اجرا چه امکاناتی داری؟ مثلاً موبایل، دوربین، لوکیشن، "
            "تصویر ثابت یا انیمیشن."
        )
    if field == "tone":
        return "لحن محتوا چطور باشد؟ صمیمی، حرفه‌ای، داستانی یا انرژی‌بخش؟"
    if field == "duration":
        return "مدت تقریبی محتوا چقدر باشد؟"
    if field == "expected_action":
        if goal:
            return f"هدف این محتوا «{goal}» است؛ در پایان دقیقاً چه اقدامی از مخاطب می‌خواهی؟"
        return (
            "در پایان، از مخاطب چه اقدام مشخصی می‌خواهی؟ مثلاً کامنت بگذارد، "
            "پیام بدهد، پست را ذخیره کند یا به یک صفحه برود."
        )
    return "سؤال بعدی را بپرسم؟"


PROBE_MESSAGES = {
    "domain_product": "خب، حالا دقیقاً چه محصول یا خدمتی ارائه می‌دهی؟ یک جملهٔ کوتاه کافی است.",
    "audience": "این مخاطب را کمی دقیق‌تر توصیف کن؛ مثلاً چه نقش، سن یا مرحله‌ای از کار؟",
    "concern": "کمی جزئی‌تر: این دغدغه بیشتر در چه لحظه‌ای از کار مخاطب پیش می‌آید؟",
}


def _add_message(conversation: Conversation, role: str, kind: str, content: str, meta: dict | None = None) -> Message:
    return Message.objects.create(
        conversation=conversation,
        role=role,
        kind=kind,
        content=content,
        meta=meta or {},
    )


def _question_message(
    conversation: Conversation,
    field: str,
    probe: bool = False,
    cue: str | None = None,
    grounding: TurnGrounding | None = None,
) -> Message:
    data = QUESTION_DATA.get(field, {})
    if cue:
        content = cue
    elif probe:
        content = PROBE_MESSAGES.get(field, question_for(field, conversation.brief))
    else:
        content = question_for(field, conversation.brief)
    meta = {
        "field": field,
        "label": BRIEF_LABELS.get(field, ""),
        "suggestions": data.get("suggestions", []),
        "placeholder": data.get("placeholder", ""),
        "probe": probe,
        "grounded": bool(cue),
    }
    if grounding is not None:
        meta["retrieval"] = grounding.summary
    return _add_message(
        conversation,
        Message.ROLE_ASSISTANT,
        Message.KIND_QUESTION,
        content,
        meta,
    )


def _hypothesis_message(
    conversation: Conversation,
    field: str,
    grounding: TurnGrounding | None = None,
) -> Message:
    suggestions = QUESTION_DATA.get(field, {}).get("suggestions", [])
    lines = [
        "اشکالی ندارد. برای این بخش چند فرضیه پیشنهاد می‌دهم؛ "
        "هیچ‌کدام را بدون تأیید تو در بریف ثبت نمی‌کنم:",
    ]
    for index, item in enumerate(suggestions, start=1):
        lines.append(f"{index}) {item}")
    lines.append("کدام به کارت نزدیک‌تر است؟ شماره یا خود جمله را بنویس.")
    meta = {
        "field": field,
        "label": BRIEF_LABELS.get(field, ""),
        "suggestions": suggestions,
        "awaiting_hypothesis": True,
        "placeholder": "شماره یا جملهٔ خودت",
    }
    if grounding is not None:
        meta["retrieval"] = grounding.summary
    return _add_message(
        conversation,
        Message.ROLE_ASSISTANT,
        Message.KIND_QUESTION,
        "\n".join(lines),
        meta,
    )


def _record_user_retrieval(conversation: Conversation, grounding: TurnGrounding | None) -> None:
    """ثبت منابع بررسی‌شده روی پیام کاربر؛ فقط برای مدیر، نه برای نمایش عمومی."""
    if grounding is None or not grounding.has_hits:
        return
    user_message = (
        conversation.messages.filter(role=Message.ROLE_USER)
        .order_by("-created_at", "-id")
        .first()
    )
    if not user_message:
        return
    meta = dict(user_message.meta or {})
    meta["retrieval"] = grounding.summary
    user_message.meta = meta
    user_message.save(update_fields=["meta"])


def _maybe_grounded_probe(
    conversation: Conversation,
    state: dict,
    field: str,
    text: str,
    messages: list[Message],
    grounding: TurnGrounding | None,
) -> bool:
    """اگر مدرک روشی مرتبط وجود داشته باشد، یک سؤال تکمیلی هدفمند می‌پرسد."""
    if not grounding or not grounding.cue:
        return False
    if field not in HANDOUT_PROBE_FIELDS or not is_thin_answer(field, text):
        return False
    if field in set(state.get("probe_done") or []):
        return False
    if field in set(state.get("handout_probe_done") or []):
        return False

    state["probe_field"] = field
    done = set(state.get("handout_probe_done") or [])
    done.add(field)
    state["handout_probe_done"] = sorted(done)
    conversation.engine_state = state
    conversation.save()
    messages.append(
        _question_message(
            conversation,
            field,
            probe=True,
            cue=grounding.cue,
            grounding=grounding,
        )
    )
    return True


def build_brief_summary(brief: dict, confirmed_hypotheses: Iterable[str] | None = None) -> str:
    lines = ["بریف آماده است. یک‌بار بخوان و اگر درست است تأیید کن:"]
    for key in BRIEF_KEYS:
        value = str(brief.get(key, "") or "").strip() or "—"
        lines.append(f"• {BRIEF_LABELS[key]}: {value}")
    confirmed = [BRIEF_LABELS[key] for key in (confirmed_hypotheses or []) if key in BRIEF_LABELS]
    if confirmed:
        lines.append("")
        lines.append("این بخش‌ها با تأیید تو از گزینه‌های پیشنهادی انتخاب شده‌اند: " + "، ".join(confirmed))
    lines.append("")
    lines.append(
        "اگر چیزی را باید عوض کنی، از فرم «ویرایش بریف» استفاده کن. "
        "تا دکمهٔ «تأیید و ساخت سناریو» را نزنی، سناریویی ساخته نمی‌شود."
    )
    return "\n".join(lines)


def _brief_message(conversation: Conversation) -> Message:
    return _add_message(
        conversation,
        Message.ROLE_ASSISTANT,
        Message.KIND_BRIEF,
        build_brief_summary(conversation.brief, conversation.engine_state.get("confirmed_hypotheses")),
        {"brief": conversation.brief},
    )


def _advance(conversation: Conversation, state: dict, messages: list[Message]) -> None:
    missing = first_missing_field(conversation.brief)
    state["awaiting_hypothesis"] = None
    state["probe_field"] = None
    if missing:
        conversation.status = STATUS_COLLECTING
        state["current_field"] = missing
        conversation.engine_state = state
        conversation.save()
        messages.append(_question_message(conversation, missing))
        return

    conversation.status = STATUS_BRIEF_READY
    conversation.brief_confirmed_at = None
    state["current_field"] = None
    state.pop("show_brief_edit", None)
    conversation.engine_state = state
    conversation.save()
    messages.append(_brief_message(conversation))


def start_conversation(conversation: Conversation) -> list[Message]:
    """ثبت اولین پرسش برای گفتگوی تازه (idempotent)."""
    if conversation.messages.exists():
        return []
    field = first_missing_field(conversation.brief) or BRIEF_KEYS[0]
    state = conversation.engine_state or {}
    state["current_field"] = field
    conversation.engine_state = state
    conversation.status = STATUS_COLLECTING
    conversation.save()
    grounding = retrieve_for_turn(conversation.brief, latest_text="", field=field)
    return [_question_message(conversation, field, grounding=grounding)]


@transaction.atomic
def handle_user_message(conversation: Conversation, text: str) -> list[Message]:
    """ذخیرهٔ پاسخ کاربر و تولید پیام‌های بعدی دستیار."""
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    text = normalize_fa(text)
    messages: list[Message] = []

    if conversation.status == STATUS_GENERATING:
        messages.append(
            _add_message(
                conversation,
                Message.ROLE_ASSISTANT,
                Message.KIND_NOTICE,
                "سناریوی قبلی هنوز در حال ساخت است. چند لحظه صبر کن و بعد دوباره تلاش کن.",
            )
        )
        return messages

    if conversation.status in (STATUS_BRIEF_READY, STATUS_GENERATED):
        state = conversation.engine_state or {}
        state["show_brief_edit"] = True
        conversation.engine_state = state
        conversation.save()
        messages.append(
            _add_message(
                conversation,
                Message.ROLE_ASSISTANT,
                Message.KIND_NOTICE,
                "بازخوردت را ثبت کردم. برای اینکه بریف دقیق بماند، بخش موردنظر را از "
                "فرم «ویرایش بریف» عوض کن؛ بعد از ذخیره، بریف جدید را دوباره تأیید می‌کنیم. "
                "برای ساخت هم باید دکمهٔ «تأیید و ساخت سناریو» را بزنی.",
            )
        )
        return messages

    state = conversation.engine_state or {}
    field = state.get("current_field") or first_missing_field(conversation.brief)
    if not field:
        _advance(conversation, state, messages)
        return messages

    suggestions = QUESTION_DATA.get(field, {}).get("suggestions", [])
    awaiting = state.get("awaiting_hypothesis")
    probe_field = state.get("probe_field")
    probe_done = set(state.get("probe_done") or [])
    confirmed_hypotheses = set(state.get("confirmed_hypotheses") or [])

    # ۱) کاربر در حال انتخاب از میان فرضیه‌هاست.
    if awaiting == field:
        if is_negative(text):
            state["awaiting_hypothesis"] = None
            conversation.engine_state = state
            conversation.save()
            messages.append(
                _add_message(
                    conversation,
                    Message.ROLE_ASSISTANT,
                    Message.KIND_NOTICE,
                    "باشه. خودت در یک جملهٔ کوتاه بنویس؛ حتی اگر ناقص باشد، با هم کاملش می‌کنیم.",
                )
            )
            grounding = retrieve_for_turn(conversation.brief, latest_text=text, field=field)
            _record_user_retrieval(conversation, grounding)
            messages.append(_question_message(conversation, field, grounding=grounding))
            return messages

        choice = parse_choice(text, suggestions)
        if choice:
            conversation.brief[field] = suggestions[choice - 1]
            confirmed_hypotheses.add(field)
        elif is_dont_know(text):
            messages.append(
                _add_message(
                    conversation,
                    Message.ROLE_ASSISTANT,
                    Message.KIND_NOTICE,
                    "برای اینکه از خودم چیزی نسازم، یکی از شماره‌ها را انتخاب کن یا خودت جمله‌ای بنویس.",
                )
            )
            return messages
        else:
            conversation.brief[field] = text

        state["awaiting_hypothesis"] = None
        state["confirmed_hypotheses"] = sorted(confirmed_hypotheses)
        if field == "domain_product":
            conversation.title = title_from_domain(conversation.brief[field])
        grounding = retrieve_for_turn(conversation.brief, latest_text=text, field=field)
        _record_user_retrieval(conversation, grounding)
        _advance(conversation, state, messages)
        return messages

    # ۲) کاربر جواب نمی‌داند؛ فرضیه پیشنهاد می‌دهیم و ثبت نمی‌کنیم.
    if is_dont_know(text) and probe_field != field:
        grounding = retrieve_for_turn(conversation.brief, latest_text=text, field=field)
        if suggestions:
            state["awaiting_hypothesis"] = field
            conversation.engine_state = state
            conversation.save()
            messages.append(_hypothesis_message(conversation, field, grounding=grounding))
        else:
            messages.append(
                _add_message(
                    conversation,
                    Message.ROLE_ASSISTANT,
                    Message.KIND_NOTICE,
                    "برای این بخش نمی‌توانم از خودم چیزی بسازم. یک مثال کوچک یا حتی یک جملهٔ "
                    "ناقص بنویس تا با هم کاملش کنیم.",
                    {"retrieval": grounding.summary} if grounding.has_hits else None,
                )
            )
        return messages

    # ۳) پاسخ به پرسش تکمیلی (probe).
    if probe_field == field and field not in probe_done:
        if is_dont_know(text):
            probe_done.add(field)
        else:
            existing = str(conversation.brief.get(field, "") or "").strip()
            conversation.brief[field] = f"{existing} — {text}" if existing else text
            probe_done.add(field)
        state["probe_done"] = sorted(probe_done)
        state["probe_field"] = None
        if field == "domain_product":
            conversation.title = title_from_domain(conversation.brief[field])
        grounding = retrieve_for_turn(conversation.brief, latest_text=text, field=field)
        _record_user_retrieval(conversation, grounding)
        _advance(conversation, state, messages)
        return messages

    # ۴) پاسخ تازه به سؤال اصلی.
    conversation.brief[field] = text
    if field == "domain_product":
        conversation.title = title_from_domain(text)

    grounding = retrieve_for_turn(conversation.brief, latest_text=text, field=field)
    _record_user_retrieval(conversation, grounding)

    # اگر جزوه‌ها موضوع روشی مرتبطی داشته باشند، اول یک سؤال هدفمند می‌پرسیم.
    if _maybe_grounded_probe(conversation, state, field, text, messages, grounding):
        return messages

    should_probe = False
    if field in PROBE_MESSAGES and field not in probe_done:
        if field == "domain_product" and len(text) < 12:
            should_probe = True
        elif field == "audience" and len(text) < 10:
            should_probe = True
        elif field == "concern" and len(text) < 24:
            should_probe = True

    if should_probe:
        state["probe_field"] = field
        conversation.engine_state = state
        conversation.save()
        messages.append(_question_message(conversation, field, probe=True, grounding=grounding))
        return messages

    _advance(conversation, state, messages)
    return messages


def apply_brief_update(conversation: Conversation, cleaned_brief: dict) -> list[Message]:
    """به‌روزرسانی بریف از فرم ویرایش؛ همیشه تأیید دوباره لازم است."""
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        conversation.brief = {key: value for key, value in cleaned_brief.items() if str(value).strip()}
        conversation.brief_confirmed_at = None
        state = conversation.engine_state or {}
        state["awaiting_hypothesis"] = None
        state["probe_field"] = None
        state["show_brief_edit"] = False
        conversation.engine_state = state
        messages: list[Message] = []

        missing = first_missing_field(conversation.brief)
        if missing:
            conversation.status = STATUS_COLLECTING
            state["current_field"] = missing
            conversation.engine_state = state
            conversation.save()
            messages.append(
                _add_message(
                    conversation,
                    Message.ROLE_ASSISTANT,
                    Message.KIND_NOTICE,
                    "بریف به‌روز شد، اما هنوز چند بخش تکمیل‌نشده دارد. "
                    "برای ادامه به سؤال بعدی پاسخ بده.",
                )
            )
            grounding = retrieve_for_turn(conversation.brief, latest_text="", field=missing)
            messages.append(_question_message(conversation, missing, grounding=grounding))
        else:
            conversation.status = STATUS_BRIEF_READY
            state["current_field"] = None
            conversation.engine_state = state
            conversation.save()
            messages.append(
                _add_message(
                    conversation,
                    Message.ROLE_ASSISTANT,
                    Message.KIND_NOTICE,
                    "بریف به‌روز شد. سناریوی قبلی برای مرجع می‌ماند؛ برای ساخت نسخهٔ جدید "
                    "باید بریف تازه را تأیید کنی.",
                )
            )
            messages.append(_brief_message(conversation))
        return messages


def mark_generation_started(conversation: Conversation) -> None:
    conversation.status = STATUS_GENERATING
    conversation.save(update_fields=["status", "updated_at"])


def finish_generation_success(conversation: Conversation, scenario_text: str) -> Message:
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        conversation.status = STATUS_GENERATED
        conversation.generated_at = timezone.now()
        conversation.brief_confirmed_at = conversation.brief_confirmed_at or timezone.now()
        state = conversation.engine_state or {}
        state["current_field"] = None
        conversation.engine_state = state
        conversation.save()
        return _add_message(
            conversation,
            Message.ROLE_ASSISTANT,
            Message.KIND_SCENARIO,
            scenario_text,
            {"brief": conversation.brief, "generated_at": conversation.generated_at.isoformat()},
        )


def finish_generation_error(conversation: Conversation, user_message: str, code: str = "error") -> Message:
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
        conversation.status = STATUS_BRIEF_READY
        conversation.save(update_fields=["status", "updated_at"])
        return _add_message(
            conversation,
            Message.ROLE_ASSISTANT,
            Message.KIND_ERROR,
            user_message,
            {"code": code},
        )


def add_notice(conversation: Conversation, content: str, meta: dict | None = None) -> Message:
    return _add_message(conversation, Message.ROLE_ASSISTANT, Message.KIND_NOTICE, content, meta)


def title_from_domain(value: str) -> str:
    value = SPACES.sub(" ", normalize_fa(value)).strip()
    if not value:
        return "گفتگوی جدید"
    if len(value) > 70:
        value = value[:69].rstrip() + "…"
    return value


def current_suggestions(conversation: Conversation) -> list[str]:
    if conversation.status != STATUS_COLLECTING:
        return []
    state = conversation.engine_state or {}
    field = state.get("current_field")
    return list(QUESTION_DATA.get(field, {}).get("suggestions", [])) if field else []


def current_field_info(conversation: Conversation) -> dict:
    state = conversation.engine_state or {}
    field = state.get("current_field")
    return {
        "key": field,
        "label": BRIEF_LABELS.get(field, ""),
        "awaiting_hypothesis": bool(state.get("awaiting_hypothesis")),
    }
