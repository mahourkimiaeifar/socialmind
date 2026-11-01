from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from knowledge.models import Chunk, Document, Page
from knowledge.services import build_query_from_brief, search_chunks

from .constants import (
    STATUS_BRIEF_READY,
    STATUS_COLLECTING,
    STATUS_GENERATED,
    STATUS_GENERATING,
    STATUS_LABELS,
)
from .forms import BriefForm, ChatMessageForm
from .models import Conversation, Message, ScenarioSource
from .services import agent
from .services.llm import LLMError, generate_scenario

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# کمک‌کننده‌ها
# ---------------------------------------------------------------------------

def _ensure_session(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _owned_conversations(request):
    """گفتگوهای قابل مشاهده برای همین درخواست.

    - کاربر واردشده فقط گفتگوهای خودش را می‌بیند؛ گفتگوهای مهمانِ همین نشست هم
      فقط اگر به کاربری تعلق نداشته باشند قابل مشاهده‌اند.
    - کاربر مهمان فقط گفتگوهای بدون کاربرِ همین نشست را می‌بیند.
    """
    key = _ensure_session(request)
    if request.user.is_authenticated:
        return Conversation.objects.filter(
            Q(user=request.user) | Q(user__isnull=True, session_key=key)
        ).distinct()
    return Conversation.objects.filter(session_key=key, user__isnull=True)


def _get_conversation(request, pk: int) -> Conversation:
    return get_object_or_404(_owned_conversations(request), pk=pk)


def _wants_json(request) -> bool:
    return (
        "application/json" in (request.headers.get("Accept") or "")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _json_error(message: str, status: int = 400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _brief_context(request, conversation: Conversation) -> dict:
    missing = agent.missing_labels(conversation.brief)
    can_generate = conversation.status == STATUS_BRIEF_READY and not missing
    return {
        "conversation": conversation,
        "brief_items": conversation.brief_items(),
        "missing_labels": missing,
        "remaining_count": len(missing),
        "can_generate": can_generate,
        "brief_form": BriefForm(initial=conversation.brief),
        "show_brief_edit": bool(
            conversation.engine_state.get("show_brief_edit") or request.GET.get("edit") == "1"
        ),
        "max_message_length": settings.MESSAGE_MAX_LENGTH,
        "field_info": agent.current_field_info(conversation),
        "suggestions": agent.current_suggestions(conversation),
        "api_configured": bool(settings.OPENAI_API_KEY),
    }


def _state_payload(
    request,
    conversation: Conversation,
    new_messages: list[Message] | None = None,
    status_code: int = 200,
    **extra,
):
    new_messages = new_messages or []
    messages_html = "".join(
        render_to_string(
            "studio/_message.html",
            {"message": item, "conversation": conversation, "request": request},
            request=request,
        )
        for item in new_messages
    )
    brief_context = _brief_context(request, conversation)
    brief_html = render_to_string("studio/_brief_panel.html", brief_context, request=request)
    suggestions_html = render_to_string(
        "studio/_suggestions.html",
        {
            "conversation": conversation,
            "suggestions": agent.current_suggestions(conversation),
            "request": request,
        },
        request=request,
    )
    field_info = agent.current_field_info(conversation)
    payload = {
        "ok": True,
        "messages_html": messages_html,
        "brief_html": brief_html,
        "suggestions_html": suggestions_html,
        "status": conversation.status,
        "status_label": STATUS_LABELS.get(conversation.status, conversation.status),
        "title": conversation.title,
        "progress": conversation.brief_progress,
        "progress_total": conversation.brief_total,
        "progress_percent": conversation.brief_percent,
        "remaining_count": len(agent.missing_labels(conversation.brief)),
        "can_generate": conversation.status == STATUS_BRIEF_READY
        and not agent.missing_labels(conversation.brief),
        "show_brief_edit": bool(conversation.engine_state.get("show_brief_edit")),
        "brief_complete": not agent.missing_labels(conversation.brief),
        "current_field_label": field_info["label"],
    }
    payload.update(extra)
    return JsonResponse(payload, status=status_code)


# ---------------------------------------------------------------------------
# صفحات
# ---------------------------------------------------------------------------

def dashboard(request):
    _ensure_session(request)
    conversations = _owned_conversations(request)
    stats = {
        "conversation_count": conversations.count(),
        "scenario_count": conversations.filter(status=STATUS_GENERATED).count(),
        "document_count": Document.objects.count(),
        "page_count": Page.objects.count(),
        "chunk_count": Chunk.objects.count(),
        "scanned_count": Document.objects.filter(is_scanned=True).count(),
        "api_configured": bool(settings.OPENAI_API_KEY),
    }
    recent = list(conversations.order_by("-updated_at")[:5])
    return render(
        request,
        "dashboard/home.html",
        {
            "active_nav": "dashboard",
            "stats": stats,
            "recent_conversations": recent,
            "now": timezone.now(),
            "max_conversations": settings.MAX_CONVERSATIONS_PER_SESSION,
        },
    )


def studio_index(request):
    _ensure_session(request)
    query = (request.GET.get("q") or "").strip()[:100]
    queryset = _owned_conversations(request).order_by("-updated_at")
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query) | Q(messages__content__icontains=query)
        ).distinct()
    conversations = list(queryset[:60])
    return render(
        request,
        "studio/index.html",
        {
            "active_nav": "studio",
            "conversations": conversations,
            "query": query,
            "has_conversations": bool(conversations),
            "max_conversations": settings.MAX_CONVERSATIONS_PER_SESSION,
            "can_start": _owned_conversations(request).count() < settings.MAX_CONVERSATIONS_PER_SESSION,
            "api_configured": bool(settings.OPENAI_API_KEY),
        },
    )


@require_POST
def studio_new(request):
    key = _ensure_session(request)
    if _owned_conversations(request).count() >= settings.MAX_CONVERSATIONS_PER_SESSION:
        messages.error(
            request,
            f"سقف {settings.MAX_CONVERSATIONS_PER_SESSION} گفتگو برای هر نشست پر شده است. "
            "یکی از گفتگوهای قبلی را حذف کن.",
        )
        return redirect("studio_index")

    conversation = Conversation.objects.create(
        session_key=key,
        user=request.user if request.user.is_authenticated else None,
        title="گفتگوی جدید",
        status=STATUS_COLLECTING,
    )
    agent.start_conversation(conversation)
    return redirect("conversation_detail", pk=conversation.pk)


def conversation_detail(request, pk: int):
    conversation = _get_conversation(request, pk)
    message_list = list(conversation.messages.all())
    brief_context = _brief_context(request, conversation)
    context = {
        "active_nav": "studio",
        "conversation": conversation,
        "message_list": message_list,
        "history": list(_owned_conversations(request).order_by("-updated_at")[:40]),
        "query": "",
        "has_previous_scenario": any(item.kind == Message.KIND_SCENARIO for item in message_list),
        "remaining_messages": max(
            0,
            settings.MAX_USER_MESSAGES_PER_CONVERSATION
            - conversation.messages.filter(role=Message.ROLE_USER).count(),
        ),
        "max_user_messages": settings.MAX_USER_MESSAGES_PER_CONVERSATION,
        "api_configured": bool(settings.OPENAI_API_KEY),
        **brief_context,
    }
    return render(request, "studio/conversation.html", context)


@require_POST
def conversation_message(request, pk: int):
    conversation = _get_conversation(request, pk)
    form = ChatMessageForm(request.POST)
    if not form.is_valid():
        error = next(iter(form.errors.values()))[0]
        if _wants_json(request):
            return _json_error(error, 400)
        messages.error(request, error)
        return redirect("conversation_detail", pk=conversation.pk)

    text = form.cleaned_data["text"]
    client_id = (form.cleaned_data.get("client_id") or "").strip()[:64]

    if client_id:
        existing = conversation.messages.filter(client_id=client_id).first()
        if existing:
            turn = list(
                conversation.messages.filter(id__gte=existing.id).order_by("created_at", "id")
            )
            return _state_payload(request, conversation, turn, duplicate=True)

    user_message_count = conversation.messages.filter(role=Message.ROLE_USER).count()
    if user_message_count >= settings.MAX_USER_MESSAGES_PER_CONVERSATION:
        message = (
            f"تعداد پیام‌های این گفتگو به سقف {settings.MAX_USER_MESSAGES_PER_CONVERSATION} رسیده است. "
            "یک گفتگوی جدید بساز."
        )
        if _wants_json(request):
            return _json_error(message, 429)
        messages.error(request, message)
        return redirect("conversation_detail", pk=conversation.pk)

    if conversation.messages.count() >= settings.MAX_MESSAGES_PER_CONVERSATION:
        message = "حجم این گفتگو به سقف مجاز رسیده است. یک گفتگوی جدید بساز."
        if _wants_json(request):
            return _json_error(message, 429)
        messages.error(request, message)
        return redirect("conversation_detail", pk=conversation.pk)

    if settings.MESSAGE_COOLDOWN_SECONDS > 0:
        last_user = (
            conversation.messages.filter(role=Message.ROLE_USER)
            .order_by("-created_at")
            .first()
        )
        if last_user and (timezone.now() - last_user.created_at).total_seconds() < settings.MESSAGE_COOLDOWN_SECONDS:
            message = "کمی صبر کن و بعد پیام بعدی را بفرست."
            if _wants_json(request):
                return _json_error(message, 429)
            messages.error(request, message)
            return redirect("conversation_detail", pk=conversation.pk)

    revision = conversation.status in (STATUS_BRIEF_READY, STATUS_GENERATED)
    user_message = Message.objects.create(
        conversation=conversation,
        role=Message.ROLE_USER,
        kind=Message.KIND_FEEDBACK if revision else Message.KIND_NOTICE,
        content=text,
        client_id=client_id,
    )

    try:
        assistant_messages = agent.handle_user_message(conversation, text)
    except Exception:  # noqa: BLE001
        logger.exception("Agent failure in conversation=%s", conversation.pk)
        assistant_messages = [
            agent.add_notice(
                conversation,
                "خطای غیرمنتظره‌ای در پردازش پیام رخ داد. پیام تو حفظ شده است؛ دوباره تلاش کن.",
                {"code": "agent_error"},
            )
        ]

    conversation.refresh_from_db()
    new_messages = [user_message] + list(assistant_messages)

    if _wants_json(request):
        return _state_payload(request, conversation, new_messages)

    return redirect("conversation_detail", pk=conversation.pk)


@require_POST
def conversation_generate(request, pk: int):
    conversation = _get_conversation(request, pk)

    if request.POST.get("confirm") != "1":
        return _json_error("برای ساخت سناریو باید دکمهٔ «تأیید و ساخت سناریو» را بزنی.", 400)

    if conversation.status == STATUS_GENERATING:
        return _json_error("سناریوی قبلی هنوز در حال ساخت است. چند لحظه صبر کن.", 409)

    if conversation.status == STATUS_GENERATED:
        return _json_error(
            "برای این بریف یک سناریو ساخته شده است. اگر می‌خواهی نسخهٔ جدید بسازی، "
            "اول بریف را ویرایش و دوباره تأیید کن.",
            409,
        )

    if conversation.status != STATUS_BRIEF_READY:
        return _json_error("ابتدا بریف را کامل کن؛ هنوز اطلاعات اصلی ناقص است.", 409)

    missing = agent.missing_labels(conversation.brief)
    if missing:
        return _json_error(
            "این بخش‌ها هنوز کامل نیستند: " + "، ".join(missing),
            409,
        )

    query = build_query_from_brief(conversation.brief)
    hits = search_chunks(query, limit=settings.SCENARIO_MAX_SOURCES)
    if not hits:
        notice = agent.add_notice(
            conversation,
            "در جزوه‌ها برای این بریف مدرک روشی کافی پیدا نکردم؛ برای اینکه روش را از خودم نسازم، "
            "یک جزئیات واقعی دیگر به دغدغهٔ مخاطب یا هدف محتوا اضافه کن و بعد دوباره تأیید کن.",
            {"code": "no_sources"},
        )
        conversation.status = STATUS_BRIEF_READY
        conversation.save(update_fields=["status", "updated_at"])
        conversation.refresh_from_db()
        return _state_payload(
            request,
            conversation,
            [notice],
            ok=False,
            error="مدرک روشی کافی در جزوه‌ها پیدا نشد.",
            error_code="no_sources",
        )

    unique_sources = []
    seen_sources = set()
    for hit in hits:
        source_key = (hit.chunk.document.file_name, hit.chunk.page.number)
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        unique_sources.append(hit)
    source_texts = [hit.chunk.text for hit in hits]

    agent.mark_generation_started(conversation)

    try:
        scenario_text = generate_scenario(conversation.brief, source_texts)
    except LLMError as exc:
        error_message = agent.finish_generation_error(conversation, exc.user_message, exc.code)
        conversation.refresh_from_db()
        return _state_payload(
            request,
            conversation,
            [error_message],
            ok=False,
            error=exc.user_message,
            error_code=exc.code,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected generation failure conversation=%s", conversation.pk)
        message = "خطای غیرمنتظره‌ای در ساخت سناریو رخ داد. بریف و پیام‌های تو حفظ شده‌اند؛ دوباره تلاش کن."
        error_message = agent.finish_generation_error(conversation, message, "unexpected")
        conversation.refresh_from_db()
        return _state_payload(
            request,
            conversation,
            [error_message],
            status_code=500,
            ok=False,
            error=message,
            error_code="unexpected",
        )

    with transaction.atomic():
        scenario_message = agent.finish_generation_success(conversation, scenario_text)
        for hit in unique_sources:
            ScenarioSource.objects.get_or_create(
                message=scenario_message,
                document_name=hit.chunk.document.file_name,
                page_number=hit.chunk.page.number,
                defaults={"document": hit.chunk.document},
            )

    conversation.refresh_from_db()
    return _state_payload(
        request,
        conversation,
        [scenario_message],
        scenario_ready=True,
        sources_count=len(unique_sources),
    )


@require_POST
def conversation_update_brief(request, pk: int):
    conversation = _get_conversation(request, pk)
    form = BriefForm(request.POST)
    if not form.is_valid():
        error = next(iter(form.errors.values()))[0]
        if _wants_json(request):
            return _json_error(error, 400)
        messages.error(request, error)
        return redirect("conversation_detail", pk=conversation.pk)

    agent.apply_brief_update(conversation, form.cleaned_brief())
    conversation.refresh_from_db()

    if _wants_json(request):
        return _state_payload(request, conversation, [])

    messages.success(request, "بریف به‌روز شد؛ اگر کامل است، دوباره تأیید کن.")
    url = reverse("conversation_detail", args=[conversation.pk])
    return redirect(f"{url}#brief-panel")


@require_POST
def conversation_delete(request, pk: int):
    conversation = _get_conversation(request, pk)
    conversation.delete()
    messages.success(request, "گفتگو حذف شد.")
    return redirect("studio_index")


def help_view(request):
    return render(
        request,
        "help.html",
        {
            "active_nav": "help",
            "message_max_length": settings.MESSAGE_MAX_LENGTH,
            "max_user_messages": settings.MAX_USER_MESSAGES_PER_CONVERSATION,
        },
    )


def health(request):
    try:
        Document.objects.count()
        Conversation.objects.count()
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


def csrf_failure(request, reason=""):
    if _wants_json(request):
        return JsonResponse(
            {
                "ok": False,
                "error": "نشست امنیتی منقضی یا نامعتبر شده است. صفحه را دوباره بارگذاری کن و دوباره تلاش کن.",
            },
            status=403,
        )
    return render(request, "403_csrf.html", status=403)


def not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)
