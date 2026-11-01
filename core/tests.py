from __future__ import annotations

from http.client import RemoteDisconnected
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from knowledge.models import Chunk, Document, Page
from knowledge.pdf import make_search_text

from .constants import BRIEF_KEYS, STATUS_BRIEF_READY, STATUS_COLLECTING, STATUS_GENERATED
from .models import Conversation, Message, ScenarioSource
from .services import agent
from .services import llm as llm_service
from .services.llm import LLMError

User = get_user_model()

ANSWERS = {
    "domain_product": "آموزش زبان انگلیسی برای بزرگسالان شاغل",
    "audience": "والدین شاغلی که وقت کافی برای تمرین ندارند",
    "concern": "هر بار شروع می‌کند و بعد از دو روز رها می‌کند",
    "message": "با ده دقیقه در روز هم می‌شود شروع کرد",
    "goal": "مخاطب یک قدم کوچک را امتحان کند",
    "capabilities": "فقط موبایل و نور طبیعی دارم",
    "tone": "صمیمی و ساده",
    "duration": "۶۰ ثانیه",
    "expected_action": "در کامنت بنویسد بزرگ‌ترین مانعش چیست",
}

SCENARIO_TEXT = """## ایده و پیام اصلی
شروع کوچک و روزانه، به‌جای برنامهٔ کامل و شکست‌خورده.

## دغدغهٔ مخاطب
والدین شاغل احساس می‌کنند وقت کافی برای تمرین ندارند.

## تکنیک انتخابی و دلیلش
تکنیک «مسئلهٔ کوچک قابل حل» چون دغدغهٔ واقعی مخاطب را در چند ثانیه نشان می‌دهد.

## قلاب
«اگر هر بار بعد از دو روز رها می‌کنی، مشکل اراده نیست.»

## صحنه‌ها
### صحنهٔ ۱ — ۰ تا ۵ ثانیه
- تصویر/حرکت دوربین: نمای نزدیک از دفتر و ساعت
- متن گوینده: اگر بعد از دو روز رها می‌کنی، مشکل اراده نیست.
- نوشتهٔ روی تصویر: مشکل اراده نیست

### صحنهٔ ۲ — ۵ تا ۲۵ ثانیه
- تصویر/حرکت دوربین: موبایل روی میز
- متن گوینده: ده دقیقه هم شروع است.
- نوشتهٔ روی تصویر: ده دقیقه کافی است

## دعوت به اقدام (CTA)
در کامنت بنویس بزرگ‌ترین مانع شروع تو چیست.

## کپشن پیشنهادی
یک قدم کوچک امروز، بهتر از برنامهٔ کامل فرداست.
"""


def create_conversation(client: Client) -> Conversation:
    response = client.post(reverse("studio_new"))
    assert response.status_code == 302, response.status_code
    pk = int(response["Location"].rstrip("/").split("/")[-1])
    return Conversation.objects.get(pk=pk)


def fill_brief(client: Client, conversation: Conversation) -> None:
    for key in BRIEF_KEYS:
        response = client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": ANSWERS[key]},
            HTTP_ACCEPT="application/json",
        )
        assert response.status_code == 200, response.content[:300]
    conversation.refresh_from_db()


def seed_handout(page_number: int = 3, text: str | None = None) -> tuple[Document, Page, Chunk]:
    document = Document.objects.create(
        file_name="جزوه-محرمانه-روش.pdf",
        source_path="C:/private/جزوه-محرمانه-روش.pdf",
        file_hash="b" * 64,
        file_size=2048,
        page_count=5,
        text_page_count=5,
    )
    page_text = text or (
        "قلاب دغدغه مخاطب آموزش زبان والدین شاغل تمرین سناریو "
        "ساختار صحنه پیام دعوت به اقدام."
    )
    page = Page.objects.create(
        document=document,
        number=page_number,
        text=page_text,
        char_count=len(page_text),
    )
    chunk = Chunk.objects.create(
        document=document,
        page=page,
        order=1,
        text=page_text,
        search_text=make_search_text(page_text),
        char_count=len(page_text),
    )
    document.chunk_count = 1
    document.save(update_fields=["chunk_count"])
    return document, page, chunk


@override_settings(
    MESSAGE_COOLDOWN_SECONDS=0,
    OPENAI_API_KEY="test-key-not-real",
    OPENAI_MODEL="test-model",
)
class PageAndAccessTests(TestCase):
    def test_public_pages_render_in_rtl_persian(self):
        for url in (reverse("dashboard"), reverse("studio_index"), reverse("help")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, 'dir="rtl"')
            self.assertContains(response, "Socia Mind")

    def test_health_endpoint_reports_database(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok"})

    def test_guest_cannot_open_another_sessions_conversation(self):
        owner = Client()
        stranger = Client()
        conversation = create_conversation(owner)

        response = stranger.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertEqual(response.status_code, 404)
        listing = stranger.get(reverse("studio_index"))
        self.assertNotContains(listing, reverse("conversation_detail", args=[conversation.pk]))

    def test_authenticated_users_only_see_their_own_conversations(self):
        user_a = User.objects.create_user("user-a", password="Pass-12345")
        user_b = User.objects.create_user("user-b", password="Pass-12345")
        client_a = Client()
        client_a.force_login(user_a)
        conversation = create_conversation(client_a)
        self.assertEqual(conversation.user, user_a)

        client_b = Client()
        client_b.force_login(user_b)
        response = client_b.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertEqual(response.status_code, 404)

    def test_user_owned_conversation_is_hidden_from_guest_with_same_session_key(self):
        user = User.objects.create_user("owner", password="Pass-12345")
        auth_client = Client()
        auth_client.force_login(user)
        conversation = create_conversation(auth_client)

        guest = Client()
        guest.get(reverse("dashboard"))
        guest_key = guest.session.session_key
        conversation.session_key = guest_key
        conversation.save(update_fields=["session_key"])

        response = guest.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertEqual(response.status_code, 404)

    def test_scenario_generation_requires_a_confirmed_ready_brief(self):
        conversation = create_conversation(self.client)
        response = self.client.post(
            reverse("conversation_generate", args=[conversation.pk]),
            {"confirm": "1"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(conversation.messages.filter(kind=Message.KIND_SCENARIO).exists())

    def test_generation_without_confirm_button_is_rejected_even_with_complete_brief(self):
        conversation = create_conversation(self.client)
        fill_brief(self.client, conversation)
        seed_handout()
        response = self.client.post(
            reverse("conversation_generate", args=[conversation.pk]),
            {},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("تأیید", response.json()["error"])
        self.assertFalse(conversation.messages.filter(kind=Message.KIND_SCENARIO).exists())

    def test_no_sources_keeps_brief_ready_and_adds_honest_notice(self):
        conversation = create_conversation(self.client)
        fill_brief(self.client, conversation)
        response = self.client.post(
            reverse("conversation_generate", args=[conversation.pk]),
            {"confirm": "1"},
            HTTP_ACCEPT="application/json",
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error_code"], "no_sources")
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, STATUS_BRIEF_READY)
        self.assertFalse(conversation.messages.filter(kind=Message.KIND_SCENARIO).exists())
        self.assertIn("مدرک", conversation.messages.last().content)

    @patch("core.views.generate_scenario", return_value=SCENARIO_TEXT)
    def test_successful_generation_records_scenario_and_sources(self, mocked_generate):
        document, page, _chunk = seed_handout(page_number=3)
        conversation = create_conversation(self.client)
        fill_brief(self.client, conversation)

        response = self.client.post(
            reverse("conversation_generate", args=[conversation.pk]),
            {"confirm": "1"},
            HTTP_ACCEPT="application/json",
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["ok"])
        self.assertTrue(data["scenario_ready"])

        conversation.refresh_from_db()
        self.assertEqual(conversation.status, STATUS_GENERATED)
        self.assertIsNotNone(conversation.brief_confirmed_at)
        scenario = conversation.messages.filter(kind=Message.KIND_SCENARIO).last()
        self.assertIsNotNone(scenario)
        self.assertIn("تکنیک انتخابی", scenario.content)

        source = ScenarioSource.objects.get(message=scenario)
        self.assertEqual(source.document_name, document.file_name)
        self.assertEqual(source.page_number, page.number)

        self.assertTrue(mocked_generate.called)
        brief_arg, source_texts = mocked_generate.call_args.args
        self.assertEqual(brief_arg["domain_product"], ANSWERS["domain_product"])
        self.assertTrue(source_texts)
        self.assertNotIn(document.file_name, "\n".join(source_texts))

    @patch(
        "core.views.generate_scenario",
        side_effect=LLMError("invalid_key", "کلید API نامعتبر است یا دسترسی ندارد."),
    )
    def test_invalid_key_returns_clear_error_and_preserves_brief(self, _mocked):
        seed_handout()
        conversation = create_conversation(self.client)
        fill_brief(self.client, conversation)
        original_brief = dict(conversation.brief)

        response = self.client.post(
            reverse("conversation_generate", args=[conversation.pk]),
            {"confirm": "1"},
            HTTP_ACCEPT="application/json",
        )
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error_code"], "invalid_key")
        self.assertIn("کلید API", data["error"])
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, STATUS_BRIEF_READY)
        self.assertEqual(conversation.brief, original_brief)
        self.assertFalse(conversation.messages.filter(kind=Message.KIND_SCENARIO).exists())
        self.assertTrue(conversation.messages.filter(kind=Message.KIND_ERROR).exists())


@override_settings(MESSAGE_COOLDOWN_SECONDS=0, OPENAI_API_KEY="test-key-not-real")
class ConversationFlowTests(TestCase):
    def test_message_is_persisted_and_visible_after_reload(self):
        conversation = create_conversation(self.client)
        response = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "آموزش زبان انگلیسی"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            conversation.messages.filter(role=Message.ROLE_USER, content="آموزش زبان انگلیسی").exists()
        )
        page = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertContains(page, "آموزش زبان انگلیسی")

    def test_one_clear_question_per_turn_and_dependency_on_previous_answer(self):
        conversation = create_conversation(self.client)
        first_question_count = conversation.messages.filter(kind=Message.KIND_QUESTION).count()
        self.assertEqual(first_question_count, 1)

        response = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "آموزش زبان انگلیسی برای بزرگسالان"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        question = conversation.messages.filter(kind=Message.KIND_QUESTION).last()
        self.assertIn("آموزش زبان انگلیسی برای بزرگسالان", question.content)
        self.assertIn("مخاطب", question.content)

    def test_duplicate_client_id_is_idempotent(self):
        conversation = create_conversation(self.client)
        payload = {"text": "آموزش زبان", "client_id": "same-request-1"}
        first = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            payload,
            HTTP_ACCEPT="application/json",
        )
        second = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "متن تکراری", "client_id": "same-request-1"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json().get("duplicate"))
        self.assertEqual(
            conversation.messages.filter(role=Message.ROLE_USER, client_id="same-request-1").count(),
            1,
        )
        self.assertFalse(conversation.messages.filter(content="متن تکراری").exists())

    @override_settings(MESSAGE_MAX_LENGTH=20)
    def test_message_longer_than_limit_is_rejected_and_not_saved(self):
        conversation = create_conversation(self.client)
        response = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "x" * 21},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("نویسه", response.json()["error"])
        self.assertFalse(conversation.messages.filter(role=Message.ROLE_USER).exists())

    @override_settings(MAX_USER_MESSAGES_PER_CONVERSATION=2)
    def test_user_message_limit_is_enforced(self):
        conversation = create_conversation(self.client)
        for text in ("اول", "دوم"):
            response = self.client.post(
                reverse("conversation_message", args=[conversation.pk]),
                {"text": text},
                HTTP_ACCEPT="application/json",
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "سوم"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(conversation.messages.filter(role=Message.ROLE_USER).count(), 2)

    @override_settings(MAX_CONVERSATIONS_PER_SESSION=1)
    def test_conversation_limit_is_enforced(self):
        create_conversation(self.client)
        response = self.client.post(reverse("studio_new"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Conversation.objects.count(), 1)
        listing = self.client.get(reverse("studio_index"), follow=True)
        self.assertContains(listing, "سقف")

    def test_brief_edit_clears_previous_confirmation_and_can_disable_generation(self):
        conversation = create_conversation(self.client)
        fill_brief(self.client, conversation)
        conversation.brief_confirmed_at = timezone.now()
        conversation.save(update_fields=["brief_confirmed_at"])

        payload = {key: f"{value} (ویرایش‌شده)" for key, value in ANSWERS.items()}
        payload.pop("duration")
        response = self.client.post(
            reverse("conversation_update_brief", args=[conversation.pk]),
            payload,
        )
        self.assertEqual(response.status_code, 302)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, STATUS_COLLECTING)
        self.assertIsNone(conversation.brief_confirmed_at)
        self.assertNotIn("duration", conversation.brief)

    def test_feedback_after_ready_requires_editing_and_reconfirmation(self):
        conversation = create_conversation(self.client)
        fill_brief(self.client, conversation)
        response = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "دغدغه را کمی ساده‌تر کن"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, STATUS_BRIEF_READY)
        self.assertTrue(conversation.engine_state.get("show_brief_edit"))
        self.assertTrue(
            conversation.messages.filter(role=Message.ROLE_USER, kind=Message.KIND_FEEDBACK).exists()
        )

    def test_unknown_answer_proposes_hypotheses_without_recording_them(self):
        conversation = create_conversation(self.client)
        response = self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "نمی‌دانم"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.brief.get("domain_product", ""), "")
        self.assertTrue(conversation.engine_state.get("awaiting_hypothesis"))
        self.assertIn("فرضیه", conversation.messages.last().content)

        self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "۱"},
            HTTP_ACCEPT="application/json",
        )
        conversation.refresh_from_db()
        self.assertEqual(conversation.brief.get("domain_product"), "آموزش و مشاوره")
        self.assertIn("domain_product", conversation.engine_state.get("confirmed_hypotheses", []))

    def test_short_answer_gets_one_supplementary_question(self):
        conversation = create_conversation(self.client)
        self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "آموزش"},
            HTTP_ACCEPT="application/json",
        )
        conversation.refresh_from_db()
        self.assertEqual(conversation.brief.get("domain_product"), "آموزش")
        self.assertEqual(conversation.engine_state.get("probe_field"), "domain_product")
        self.assertTrue(conversation.messages.last().meta.get("probe"))

        self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": "آموزش زبان برای بزرگسالان"},
            HTTP_ACCEPT="application/json",
        )
        conversation.refresh_from_db()
        self.assertEqual(
            conversation.brief.get("domain_product"),
            "آموزش — آموزش زبان برای بزرگسالان",
        )
        self.assertIsNone(conversation.engine_state.get("probe_field"))
        self.assertEqual(conversation.status, STATUS_COLLECTING)

    def test_deleting_conversation_removes_messages_and_sources(self):
        conversation = create_conversation(self.client)
        response = self.client.post(reverse("conversation_delete", args=[conversation.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Conversation.objects.filter(pk=conversation.pk).exists())
        self.assertFalse(Message.objects.exists())


@override_settings(MESSAGE_COOLDOWN_SECONDS=0, OPENAI_API_KEY="test-key-not-real")
class CsrfAndPrivacyTests(TestCase):
    def test_csrf_is_required_for_mutating_requests(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("dashboard"))
        response = client.post(reverse("studio_new"), HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])
        self.assertIn("امنیتی", response.json()["error"])

    def test_valid_csrf_token_allows_mutating_request(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("dashboard"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("studio_new"), {"csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)

    def test_handout_text_and_filename_are_not_exposed_in_public_pages(self):
        secret_text = "متن-بسیار-محرمانه-جزوه-۹۹۹"
        document, _page, _chunk = seed_handout(page_number=7, text=secret_text)
        conversation = create_conversation(self.client)

        for url in (
            reverse("dashboard"),
            reverse("studio_index"),
            reverse("conversation_detail", args=[conversation.pk]),
        ):
            response = self.client.get(url)
            self.assertNotContains(response, secret_text)
            self.assertNotContains(response, document.file_name)
            self.assertNotContains(response, document.source_path)

    def test_api_key_value_is_never_rendered_in_html_or_json(self):
        secret_key = "sk-test-value-that-must-never-leak-123"
        with override_settings(OPENAI_API_KEY=secret_key):
            conversation = create_conversation(self.client)
            responses = [
                self.client.get(reverse("dashboard")),
                self.client.get(reverse("studio_index")),
                self.client.get(reverse("conversation_detail", args=[conversation.pk])),
            ]
        for response in responses:
            self.assertNotIn(secret_key, response.content.decode("utf-8"))

    def test_missing_key_is_reported_clearly_on_public_pages(self):
        with override_settings(OPENAI_API_KEY=""):
            response = self.client.get(reverse("studio_index"))
        self.assertContains(response, "کلید مدل تنظیم نشده")
        self.assertNotContains(response, "sk-test-value")


@override_settings(MESSAGE_COOLDOWN_SECONDS=0)
class AdminPrivacyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-test",
            email="admin@example.com",
            password="Strong-Pass-123",
        )
        self.client.force_login(self.admin)

    def test_document_admin_lists_metadata_but_not_full_text(self):
        secret_text = "متن-کامل-جزوه-که-نباید-در-ادمین-لیست-بیاید"
        document, _page, _chunk = seed_handout(page_number=4, text=secret_text)

        listing = self.client.get("/admin/knowledge/document/")
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, document.file_name)
        self.assertNotContains(listing, secret_text)

        change = self.client.get(f"/admin/knowledge/document/{document.pk}/change/")
        self.assertEqual(change.status_code, 200)
        self.assertContains(change, "تعداد نویسه")
        self.assertNotContains(change, secret_text)

    def test_conversation_admin_renders_brief_summary(self):
        conversation = create_conversation(self.client)
        conversation.brief = {"domain_product": "آموزش زبان ویژه"}
        conversation.save(update_fields=["brief"])
        response = self.client.get(f"/admin/core/conversation/{conversation.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "آموزش زبان ویژه")
        self.assertContains(response, "حوزه و محصول/خدمت")

    def test_non_staff_cannot_open_admin(self):
        self.client.logout()
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


class LlmErrorMappingTests(SimpleTestCase):
    @patch("core.services.llm.urlopen", side_effect=RemoteDisconnected("remote closed"))
    def test_dropped_connection_maps_to_clear_network_error(self, _mocked):
        with self.assertRaises(LLMError) as raised:
            llm_service._post_json("https://example.invalid/v1/responses", {}, {}, 5)
        self.assertEqual(raised.exception.code, "network")
        self.assertIn("ارتباط", raised.exception.user_message)

    @override_settings(OPENAI_API_KEY="")
    def test_missing_key_stops_generation_before_any_request(self):
        with patch("core.services.llm.urlopen") as mocked_urlopen:
            with self.assertRaises(LLMError) as raised:
                llm_service.generate_scenario({"domain_product": "آموزش"}, ["مدرک روشی"])
        self.assertEqual(raised.exception.code, "missing_key")
        mocked_urlopen.assert_not_called()


class AgentUnitTests(TestCase):
    def _conversation(self) -> Conversation:
        conversation = Conversation.objects.create(session_key="agent-test-session")
        agent.start_conversation(conversation)
        conversation.refresh_from_db()
        return conversation

    def test_start_conversation_is_idempotent(self):
        conversation = self._conversation()
        count = conversation.messages.count()
        self.assertEqual(agent.start_conversation(conversation), [])
        self.assertEqual(conversation.messages.count(), count)

    def test_hypothesis_answer_is_not_saved_until_user_picks_one(self):
        conversation = self._conversation()
        agent.handle_user_message(conversation, "نمی‌دانم")
        conversation.refresh_from_db()
        self.assertEqual(conversation.brief, {})
        self.assertTrue(conversation.engine_state.get("awaiting_hypothesis"))

        agent.handle_user_message(conversation, "گزینهٔ ۲")
        conversation.refresh_from_db()
        self.assertEqual(conversation.brief.get("domain_product"), "فروش محصول فیزیکی")
        self.assertIn("domain_product", conversation.engine_state.get("confirmed_hypotheses", []))

    def test_negative_hypothesis_answer_asks_for_own_words(self):
        conversation = self._conversation()
        agent.handle_user_message(conversation, "نمی‌دانم")
        messages = agent.handle_user_message(conversation, "هیچ‌کدام")
        conversation.refresh_from_db()
        self.assertEqual(conversation.brief, {})
        self.assertFalse(conversation.engine_state.get("awaiting_hypothesis"))
        self.assertTrue(any("خودت" in message.content for message in messages))

    def test_brief_is_ready_only_after_all_fields_are_present(self):
        conversation = self._conversation()
        for index, key in enumerate(BRIEF_KEYS):
            agent.handle_user_message(conversation, ANSWERS[key])
            conversation.refresh_from_db()
            if index < len(BRIEF_KEYS) - 1:
                self.assertEqual(conversation.status, STATUS_COLLECTING)
        self.assertEqual(conversation.status, STATUS_BRIEF_READY)
        self.assertEqual(agent.missing_labels(conversation.brief), [])


HANDOUT_QUESTION_TEXT = (
    "برای شناخت مخاطب، محصول و خدمت و ارائه را روشن کن. "
    "موقعیت روزمره، ترس و نگرانی، مانع و بهانه، باور اشتباه و اقدام را بپرس. "
    "قلاب و صحنه و پیام روشی سناریو."
)


@override_settings(
    MESSAGE_COOLDOWN_SECONDS=0,
    OPENAI_API_KEY="test-key-not-real",
    HANDOUT_RETRIEVAL_PER_TURN=True,
    HANDOUT_TURN_SOURCES=5,
)
class HandoutQuestioningTests(TestCase):
    def setUp(self):
        self.document, self.page, _chunk = seed_handout(
            page_number=5,
            text=HANDOUT_QUESTION_TEXT,
        )

    def _post(self, conversation, text):
        return self.client.post(
            reverse("conversation_message", args=[conversation.pk]),
            {"text": text},
            HTTP_ACCEPT="application/json",
        )

    def test_every_turn_retrieves_handouts_and_records_sources_for_admin(self):
        conversation = create_conversation(self.client)
        response = self._post(conversation, "آموزش زبان انگلیسی برای بزرگسالان شاغل")
        self.assertEqual(response.status_code, 200)

        user_message = (
            conversation.messages.filter(role=Message.ROLE_USER).order_by("-id").first()
        )
        retrieval = (user_message.meta or {}).get("retrieval") or {}
        self.assertTrue(retrieval.get("sources"))
        self.assertEqual(retrieval["sources"][0]["document"], self.document.file_name)
        self.assertGreaterEqual(retrieval.get("count", 0), 1)

        question = conversation.messages.filter(kind=Message.KIND_QUESTION).last()
        self.assertIn("مخاطب", question.content)
        self.assertNotIn(self.document.file_name, question.content)

    def test_short_answer_gets_handout_grounded_follow_up_without_leaking_text(self):
        conversation = create_conversation(self.client)
        response = self._post(conversation, "آموزش")
        self.assertEqual(response.status_code, 200)

        question = conversation.messages.filter(kind=Message.KIND_QUESTION).last()
        self.assertTrue(question.meta.get("grounded"))
        self.assertTrue(question.meta.get("probe"))
        self.assertIn("محصول", question.content)
        self.assertNotIn(self.document.file_name, question.content)
        self.assertNotIn(HANDOUT_QUESTION_TEXT[:25], question.content)

        page = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertNotContains(page, self.document.file_name)
        self.assertNotContains(page, HANDOUT_QUESTION_TEXT[:25])

    def test_retrieval_can_be_disabled_and_falls_back_to_plain_probe(self):
        conversation = create_conversation(self.client)
        with override_settings(HANDOUT_RETRIEVAL_PER_TURN=False):
            response = self._post(conversation, "آموزش")
        self.assertEqual(response.status_code, 200)

        question = conversation.messages.filter(kind=Message.KIND_QUESTION).last()
        self.assertFalse(question.meta.get("grounded"))
        self.assertTrue(question.meta.get("probe"))
        user_message = (
            conversation.messages.filter(role=Message.ROLE_USER).order_by("-id").first()
        )
        self.assertFalse((user_message.meta or {}).get("retrieval"))

    def test_without_evidence_no_grounded_question_is_invented(self):
        Chunk.objects.all().delete()
        Page.objects.all().delete()
        Document.objects.all().delete()

        conversation = create_conversation(self.client)
        response = self._post(conversation, "آموزش")
        self.assertEqual(response.status_code, 200)

        question = conversation.messages.filter(kind=Message.KIND_QUESTION).last()
        self.assertFalse(question.meta.get("grounded"))
        self.assertEqual(question.meta.get("retrieval", {}).get("count", 0), 0)

    def test_admin_sees_retrieved_sources_but_not_raw_handout_text(self):
        admin = User.objects.create_superuser(
            username="handout-admin",
            email="handout-admin@example.com",
            password="Strong-Pass-123",
        )
        self.client.force_login(admin)
        conversation = create_conversation(self.client)
        self._post(conversation, "آموزش زبان انگلیسی برای بزرگسالان شاغل")

        response = self.client.get(f"/admin/core/conversation/{conversation.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.document.file_name)
        self.assertNotContains(response, HANDOUT_QUESTION_TEXT[:25])
