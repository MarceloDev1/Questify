import io
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter

from accounts.tests import make_profile

from . import ai, analytics, rag, services
from .models import EMBEDDING_DIMENSIONS, DocumentChunk, Flashcard, StudyLog

BACKEND = "django.contrib.auth.backends.ModelBackend"


def unit_vector(position):
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[position] = 1.0
    return vector


def make_card(profile, **fields):
    defaults = {"question": "Pergunta?", "answer": "Resposta", "topic": "Biologia"}
    return Flashcard.objects.create(user=profile, **(defaults | fields))


class ChunkTextTests(SimpleTestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(rag.chunk_text("Texto curto."), ["Texto curto."])

    def test_empty_text_has_no_chunks(self):
        self.assertEqual(rag.chunk_text(""), [])

    def test_chunks_respect_size_and_keep_every_word(self):
        text = " ".join(f"palavra{i}" for i in range(2000))
        chunks = rag.chunk_text(text, size=500, overlap=80)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))
        self.assertEqual(set(" ".join(chunks).split()), set(text.split()))

    def test_consecutive_chunks_overlap(self):
        text = " ".join(f"palavra{i}" for i in range(500))
        first, second = rag.chunk_text(text, size=500, overlap=80)[:2]
        self.assertIn(second.split()[0], first.split())

    def test_prefers_paragraph_boundary(self):
        text = "a" * 600 + "\n\n" + "b" * 600
        chunks = rag.chunk_text(text, size=1000, overlap=100)
        self.assertEqual(chunks[0], "a" * 600)

    def test_text_without_spaces_terminates(self):
        chunks = rag.chunk_text("x" * 5000, size=1000, overlap=150)
        self.assertGreaterEqual(len(chunks), 5)


class NormalizeTextTests(SimpleTestCase):
    def test_removes_nul_and_collapses_whitespace(self):
        self.assertEqual(rag.normalize_text("a\x00b  c\r\n\n\n\nd "), "ab c\n\nd")


class ParseFlashcardsTests(SimpleTestCase):
    def test_keeps_only_valid_items_up_to_count(self):
        raw = json.dumps(
            {
                "flashcards": [
                    {"question": " P1 ", "answer": " R1 ", "difficulty": "easy"},
                    {"question": "", "answer": "sem pergunta"},
                    {"question": "sem resposta"},
                    {"question": 1, "answer": 2},
                    "lixo",
                    {"question": "P2", "answer": "R2"},
                    {"question": "P3", "answer": "R3"},
                ]
            }
        )
        items = ai._parse_flashcards(raw, count=2)
        self.assertEqual([i["question"] for i in items], ["P1", "P2"])
        self.assertEqual(items[0]["answer"], "R1")

    def test_invalid_payloads_raise_user_facing_error(self):
        for raw in ("não é json", None, "[1, 2]", '{"flashcards": "x"}'):
            with self.subTest(raw=raw), self.assertRaises(ai.AIServiceError):
                ai._parse_flashcards(raw, count=5)


class RetrievalTests(TestCase):
    def setUp(self):
        self.ana = make_profile("ana")
        self.bia = make_profile("bia")
        for profile, title, content, position in [
            (self.ana, "Bio", "fotossíntese", 0),
            (self.ana, "Bio", "mitose", 1),
            (self.ana, "Hist", "revolução", 2),
            (self.bia, "Segredo", "material da bia", 0),
        ]:
            DocumentChunk.objects.create(
                user=profile, title=title, content=content, embedding=unit_vector(position)
            )

    @mock.patch("study.ai.embed_texts")
    def test_orders_by_cosine_similarity(self, embed):
        embed.return_value = [unit_vector(1)]
        results = rag.retrieve(self.ana, "divisão celular")
        self.assertEqual(results[0].content, "mitose")

    @mock.patch("study.ai.embed_texts")
    def test_never_returns_other_users_chunks(self, embed):
        embed.return_value = [unit_vector(0)]
        contents = {chunk.content for chunk in rag.retrieve(self.ana, "x", k=10)}
        self.assertNotIn("material da bia", contents)
        self.assertEqual(len(contents), 3)

    @mock.patch("study.ai.embed_texts")
    def test_filters_by_material(self, embed):
        embed.return_value = [unit_vector(0)]
        results = rag.retrieve(self.ana, "x", title="Hist")
        self.assertEqual([c.content for c in results], ["revolução"])

    @mock.patch("study.ai.embed_texts")
    def test_without_material_does_not_call_the_api(self, embed):
        self.assertEqual(rag.retrieve(make_profile("carla"), "x"), [])
        embed.assert_not_called()


class IngestTests(TestCase):
    def setUp(self):
        self.profile = make_profile()

    @mock.patch("study.ai.embed_texts")
    def test_saves_chunks_with_embeddings(self, embed):
        embed.side_effect = lambda texts: [unit_vector(0) for _ in texts]
        count = rag.ingest_document(self.profile, "Bio", "palavra " * 500)
        self.assertGreater(count, 1)
        self.assertEqual(self.profile.chunks.filter(title="Bio").count(), count)
        self.assertEqual(len(self.profile.chunks.first().embedding), EMBEDDING_DIMENSIONS)

    def test_rejects_empty_and_oversized_material(self):
        with self.assertRaisesMessage(rag.MaterialError, "Não encontramos texto"):
            rag.ingest_document(self.profile, "Vazio", "  \n ")
        with self.assertRaisesMessage(rag.MaterialError, "muito grande"):
            rag.ingest_document(self.profile, "Grande", "x" * (rag.MAX_MATERIAL_CHARS + 1))

    def test_pdf_without_text_is_rejected(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        text = rag.extract_text(SimpleUploadedFile("vazio.pdf", buffer.read()))
        with self.assertRaisesMessage(rag.MaterialError, "Não encontramos texto"):
            rag.ingest_document(self.profile, "Escaneado", text)

    def test_corrupt_pdf_is_a_user_facing_error(self):
        with self.assertRaises(rag.MaterialError):
            rag.extract_text(SimpleUploadedFile("ruim.pdf", b"isto nao e um pdf"))

    def test_latin1_text_file(self):
        uploaded = SimpleUploadedFile("nota.txt", "fotossíntese".encode("latin-1"))
        self.assertEqual(rag.extract_text(uploaded), "fotossíntese")


class GenerateFlashcardsTests(TestCase):
    def setUp(self):
        self.profile = make_profile()
        DocumentChunk.objects.create(
            user=self.profile, title="Bio", content="conteúdo", embedding=unit_vector(0)
        )
        patcher = mock.patch("study.ai.embed_texts", return_value=[unit_vector(0)])
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch("study.ai.generate_flashcard_items")
    def test_saves_cards_and_normalizes_difficulty(self, generate):
        generate.return_value = [
            {"question": "P1", "answer": "R1", "difficulty": "hard"},
            {"question": "P2", "answer": "R2", "difficulty": "impossível"},
        ]
        rag.generate_flashcards(self.profile, "Biologia", 2)
        cards = list(self.profile.flashcards.order_by("question"))
        self.assertEqual([c.difficulty for c in cards], ["hard", "medium"])
        self.assertEqual(cards[0].topic, "Biologia")
        self.assertTrue(cards[0].is_due)

    @mock.patch("study.ai.generate_flashcard_items")
    def test_skips_duplicate_questions(self, generate):
        make_card(self.profile, question="Já existe?")
        generate.return_value = [
            {"question": "já existe?", "answer": "R", "difficulty": "easy"},
            {"question": "Nova?", "answer": "R", "difficulty": "easy"},
            {"question": "NOVA?", "answer": "R", "difficulty": "easy"},
        ]
        created = rag.generate_flashcards(self.profile, "Biologia", 3)
        self.assertEqual([c.question for c in created], ["Nova?"])

    @mock.patch("study.ai.generate_flashcard_items", return_value=[])
    def test_topic_not_covered_by_material(self, _generate):
        with self.assertRaisesMessage(rag.MaterialError, "Não encontramos conteúdo novo"):
            rag.generate_flashcards(self.profile, "Astronomia", 3)

    def test_requires_material(self):
        with self.assertRaisesMessage(rag.MaterialError, "Envie um material"):
            rag.generate_flashcards(make_profile("sem_material"), "Biologia", 3)

    @mock.patch("study.ai._client")
    def test_context_reaches_the_model(self, client):
        create = client.return_value.chat.completions.create
        content = json.dumps({"flashcards": [{"question": "P", "answer": "R"}]})
        create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        rag.generate_flashcards(self.profile, "Biologia", 1)
        prompt = create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("conteúdo", prompt)
        self.assertIn("Biologia", prompt)


class RecordAnswerTests(TestCase):
    def setUp(self):
        self.profile = make_profile()

    def test_correct_answer_gives_xp_by_difficulty(self):
        for difficulty, xp in (("easy", 5), ("medium", 10), ("hard", 20)):
            with self.subTest(difficulty=difficulty):
                card = make_card(self.profile, difficulty=difficulty)
                result = services.record_answer(self.profile, card.pk, True)
                self.assertEqual(result.xp_gained, xp)

    def test_wrong_answer_gives_small_xp_and_returns_soon(self):
        card = make_card(self.profile)
        result = services.record_answer(self.profile, card.pk, False, 7)
        self.assertEqual(result.xp_gained, services.XP_FOR_WRONG_ANSWER)
        self.assertEqual(result.next_review_label, "10 minutos")
        card.refresh_from_db()
        self.assertLess(card.next_review, timezone.now() + timedelta(minutes=11))
        log = StudyLog.objects.get(flashcard=card)
        self.assertFalse(log.is_correct)
        self.assertEqual(log.response_time_seconds, 7)

    def test_double_submit_counts_once(self):
        card = make_card(self.profile)
        self.assertIsNotNone(services.record_answer(self.profile, card.pk, True))
        self.assertIsNone(services.record_answer(self.profile, card.pk, True))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.xp, 10)
        self.assertEqual(StudyLog.objects.filter(flashcard=card).count(), 1)

    def test_cannot_answer_another_users_card(self):
        card = make_card(make_profile("bia"))
        self.assertIsNone(services.record_answer(self.profile, card.pk, True))

    def _answer_again(self, card, is_correct):
        Flashcard.objects.filter(pk=card.pk).update(next_review=timezone.now())
        return services.record_answer(self.profile, card.pk, is_correct)

    def test_interval_grows_with_correct_streak_and_resets_on_error(self):
        card = make_card(self.profile)
        labels = [self._answer_again(card, True).next_review_label for _ in range(3)]
        self.assertEqual(labels, ["1 dia", "3 dias", "7 dias"])
        self.assertEqual(self._answer_again(card, False).next_review_label, "10 minutos")
        self.assertEqual(self._answer_again(card, True).next_review_label, "1 dia")

    def test_interval_caps_at_longest_step(self):
        card = make_card(self.profile)
        for _ in range(len(services.REVIEW_INTERVALS_DAYS) + 2):
            result = self._answer_again(card, True)
        self.assertEqual(result.next_review_label, "60 dias")

    def test_level_up_is_reported(self):
        self.profile.xp = 95
        self.profile.save(update_fields=["xp"])
        result = services.record_answer(self.profile, make_card(self.profile).pk, True)
        self.assertTrue(result.leveled_up)
        self.assertEqual(result.profile.level, 2)


class StreakTests(TestCase):
    def test_next_streak_rules(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        self.assertEqual(services.next_streak(0, None, today), 1)
        self.assertEqual(services.next_streak(4, today, today), 4)
        self.assertEqual(services.next_streak(4, yesterday, today), 5)
        self.assertEqual(services.next_streak(4, today - timedelta(days=2), today), 1)

    def _log_at(self, profile, when):
        StudyLog.objects.create(
            user=profile, flashcard=make_card(profile), is_correct=True, created_at=when
        )

    def test_answering_after_a_day_extends_streak(self):
        profile = make_profile(streak=3)
        self._log_at(profile, timezone.now() - timedelta(days=1))
        result = services.record_answer(profile, make_card(profile).pk, True)
        self.assertEqual(result.profile.streak, 4)
        self.assertEqual(result.profile.current_streak, 4)

    def test_displayed_streak_drops_to_zero_after_a_missed_day(self):
        profile = make_profile(streak=9)
        self._log_at(profile, timezone.now() - timedelta(days=3))
        self.assertEqual(profile.current_streak, 0)


class AnalyticsTests(TestCase):
    def setUp(self):
        self.profile = make_profile()
        bio = make_card(self.profile, topic="Biologia")
        hist = make_card(self.profile, question="Q2", topic="História")
        none = make_card(self.profile, question="Q3", topic=None)
        now = timezone.now()
        for card, is_correct, when, seconds in [
            (bio, True, now, 10),
            (bio, True, now, 20),
            (bio, False, now - timedelta(days=2), None),
            (hist, False, now, 30),
            (none, True, now - timedelta(days=40), None),
        ]:
            StudyLog.objects.create(
                user=self.profile,
                flashcard=card,
                is_correct=is_correct,
                created_at=when,
                response_time_seconds=seconds,
            )

    def test_summary(self):
        data = analytics.summary(self.profile)
        self.assertEqual(data, {"answered": 5, "accuracy": 60, "average_seconds": 20})

    def test_summary_without_answers(self):
        data = analytics.summary(make_profile("nova"))
        self.assertEqual(data, {"answered": 0, "accuracy": None, "average_seconds": None})

    def test_by_topic(self):
        rows = analytics.performance_by_topic(self.profile)
        self.assertEqual(rows[0]["topic"], "Biologia")
        self.assertEqual((rows[0]["correct"], rows[0]["wrong"], rows[0]["accuracy"]), (2, 1, 67))
        self.assertIn("Sem tópico", [row["topic"] for row in rows])

    def test_history_fills_empty_days_and_ignores_older_answers(self):
        history = analytics.daily_history(self.profile)
        self.assertEqual(len(history["days"]), analytics.HISTORY_DAYS)
        self.assertEqual(history["days"][-1], timezone.localdate().isoformat())
        self.assertEqual(sum(history["overall"]["correct"]), 2)
        self.assertEqual(sum(history["overall"]["wrong"]), 2)
        self.assertEqual(history["byTopic"]["Biologia"]["correct"][-1], 2)
        self.assertEqual(history["byTopic"]["Biologia"]["wrong"][-3], 1)
        self.assertNotIn("Sem tópico", history["byTopic"])

    def test_does_not_mix_users(self):
        self.assertEqual(analytics.summary(make_profile("bia"))["answered"], 0)


class ViewTests(TestCase):
    def setUp(self):
        self.profile = make_profile()
        self.other = make_profile("bia")
        self.client.force_login(self.profile.user, backend=BACKEND)

    def test_all_pages_require_login(self):
        self.client.logout()
        for name in ("dashboard", "study", "flashcards", "materials"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_pages_render_empty_states(self):
        self.assertContains(self.client.get(reverse("dashboard")), "Seus gráficos aparecem aqui")
        self.assertContains(self.client.get(reverse("study")), "ainda não tem flashcards")
        self.assertContains(self.client.get(reverse("flashcards")), "ainda não enviou")
        self.assertContains(self.client.get(reverse("materials")), "Nenhum material")

    def test_dashboard_with_data_embeds_chart_payload(self):
        card = make_card(self.profile)
        services.record_answer(self.profile, card.pk, True, 5)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'id="chart-data"')
        self.assertContains(response, 'id="history-chart"')

    def test_answer_flow_returns_next_card_and_updates_hud(self):
        first = make_card(self.profile, question="Primeira?")
        second = make_card(self.profile, question="Segunda?")

        page = self.client.get(reverse("study"))
        self.assertContains(page, "Primeira?")

        revealed = self.client.get(
            reverse("study_reveal", args=[first.pk]), {"inicio": 0}, headers={"HX-Request": "true"}
        )
        self.assertContains(revealed, "Resposta")
        self.assertContains(revealed, 'name="response_time"')
        self.assertNotContains(revealed, "<html")

        response = self.client.post(
            reverse("study_answer", args=[first.pk]),
            {"is_correct": "1", "response_time": "99999"},
            headers={"HX-Request": "true"},
        )
        self.assertContains(response, "+10 XP")
        self.assertContains(response, "Segunda?")
        self.assertContains(response, 'hx-swap-oob="true"')
        self.assertContains(response, "10 XP")
        log = StudyLog.objects.get(flashcard=first)
        self.assertEqual(log.response_time_seconds, 3600)
        self.assertTrue(second.is_due)

    def test_answer_rejects_invalid_choice(self):
        card = make_card(self.profile)
        response = self.client.post(reverse("study_answer", args=[card.pk]), {"is_correct": "talvez"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StudyLog.objects.exists())

    def test_other_users_records_are_not_accessible(self):
        card = make_card(self.other, question="Segredo da bia?")
        DocumentChunk.objects.create(
            user=self.other, title="Privado", content="x", embedding=unit_vector(0)
        )
        for response in (
            self.client.get(reverse("study_reveal", args=[card.pk])),
            self.client.post(reverse("study_answer", args=[card.pk]), {"is_correct": "1"}),
            self.client.post(reverse("flashcard_delete", args=[card.pk])),
        ):
            self.assertEqual(response.status_code, 404)
        self.assertNotContains(self.client.get(reverse("flashcards")), "Segredo da bia?")
        self.assertNotContains(self.client.get(reverse("materials")), "Privado")

        self.client.post(reverse("material_delete"), {"title": "Privado"})
        self.assertTrue(DocumentChunk.objects.filter(user=self.other).exists())
        self.assertTrue(Flashcard.objects.filter(pk=card.pk).exists())

    def test_answer_requires_post(self):
        card = make_card(self.profile)
        self.assertEqual(self.client.get(reverse("study_answer", args=[card.pk])).status_code, 405)

    @mock.patch("study.ai.embed_texts")
    def test_upload_material_with_htmx_returns_panel(self, embed):
        embed.side_effect = lambda texts: [unit_vector(0) for _ in texts]
        response = self.client.post(
            reverse("materials"),
            {"title": "Biologia", "file": SimpleUploadedFile("bio.txt", b"Fotossintese e vida.")},
            headers={"HX-Request": "true"},
        )
        self.assertContains(response, "indexado em 1 trecho")
        self.assertContains(response, "Biologia")
        self.assertNotContains(response, "<html")

    def test_material_form_validation(self):
        DocumentChunk.objects.create(
            user=self.profile, title="Bio", content="x", embedding=unit_vector(0)
        )
        cases = [
            ({"title": "Novo"}, "Envie um arquivo ou cole um texto."),
            ({"title": "Bio", "text": "abc"}, "já tem um material com esse título"),
            (
                {"title": "Novo", "text": "abc", "file": SimpleUploadedFile("a.txt", b"x")},
                "não os dois",
            ),
            ({"title": "Novo", "file": SimpleUploadedFile("a.exe", b"x")}, "PDF, TXT ou Markdown"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                self.assertContains(self.client.post(reverse("materials"), data), message)

    @mock.patch("study.ai.embed_texts", side_effect=ai.AIServiceError("Falha simulada."))
    def test_ai_failure_keeps_form_and_shows_message(self, _embed):
        response = self.client.post(reverse("materials"), {"title": "Bio", "text": "conteúdo"})
        self.assertContains(response, "Falha simulada.")
        self.assertContains(response, 'value="Bio"')
        self.assertFalse(DocumentChunk.objects.exists())

    @mock.patch("study.rag.generate_flashcards")
    def test_generate_passes_selected_material(self, generate):
        DocumentChunk.objects.create(
            user=self.profile, title="Bio", content="x", embedding=unit_vector(0)
        )
        generate.return_value = [object(), object()]
        response = self.client.post(
            reverse("flashcards"),
            {"topic": "Células", "material": "Bio", "count": "2"},
            headers={"HX-Request": "true"},
        )
        self.assertContains(response, "2 flashcards criados.")
        generate.assert_called_once_with(self.profile, "Células", 2, title="Bio")

    def test_generate_rejects_material_of_another_user(self):
        DocumentChunk.objects.create(
            user=self.other, title="Privado", content="x", embedding=unit_vector(0)
        )
        with mock.patch("study.rag.generate_flashcards") as generate:
            self.client.post(
                reverse("flashcards"), {"topic": "x", "material": "Privado", "count": "1"}
            )
        generate.assert_not_called()

    def test_delete_flashcard(self):
        card = make_card(self.profile)
        self.client.post(reverse("flashcard_delete", args=[card.pk]))
        self.assertFalse(Flashcard.objects.filter(pk=card.pk).exists())
