from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.tests import make_profile

from . import duels
from .models import Duel, Flashcard, StudyLog

BACKEND = "django.contrib.auth.backends.ModelBackend"


def log_answer(profile, difficulty="medium", is_correct=True, at=None):
    card = Flashcard.objects.create(
        user=profile, question="P?", answer="R", difficulty=difficulty
    )
    return StudyLog.objects.create(
        user=profile, flashcard=card, is_correct=is_correct, created_at=at or timezone.now()
    )


def start_duel(challenger, opponent, days=7):
    duel = duels.challenge(challenger, opponent.username, days)
    return duels.respond(duel.pk, opponent, accept=True)


class ChallengeTests(TestCase):
    def setUp(self):
        self.ana = make_profile("ana")
        self.bia = make_profile("bia")

    def test_creates_pending_duel(self):
        duel = duels.challenge(self.ana, "BIA", 7)
        self.assertEqual(duel.status, Duel.Status.PENDING)
        self.assertEqual(duel.opponent, self.bia)

    def test_unknown_user_and_self_are_rejected(self):
        with self.assertRaises(duels.DuelError):
            duels.challenge(self.ana, "ninguem", 7)
        with self.assertRaises(duels.DuelError):
            duels.challenge(self.ana, "ana", 7)

    def test_invalid_duration_is_rejected(self):
        with self.assertRaises(duels.DuelError):
            duels.challenge(self.ana, "bia", 365)

    def test_only_one_open_duel_per_pair_in_either_direction(self):
        duels.challenge(self.ana, "bia", 7)
        with self.assertRaises(duels.DuelError):
            duels.challenge(self.ana, "bia", 3)
        with self.assertRaises(duels.DuelError):
            duels.challenge(self.bia, "ana", 3)

    def test_finished_duel_allows_a_rematch(self):
        duel = start_duel(self.ana, self.bia)
        Duel.objects.filter(pk=duel.pk).update(ends_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(duels.challenge(self.ana, "bia", 7).status, Duel.Status.PENDING)


class RespondTests(TestCase):
    def setUp(self):
        self.ana = make_profile("ana")
        self.bia = make_profile("bia")
        self.cris = make_profile("cris")
        self.duel = duels.challenge(self.ana, "bia", 7)

    def test_accept_starts_the_clock(self):
        duel = duels.respond(self.duel.pk, self.bia, accept=True)
        self.assertEqual(duel.status, Duel.Status.ACTIVE)
        self.assertEqual(duel.ends_at - duel.starts_at, timedelta(days=7))

    def test_decline(self):
        duel = duels.respond(self.duel.pk, self.bia, accept=False)
        self.assertEqual(duel.status, Duel.Status.DECLINED)

    def test_only_the_opponent_can_respond_and_only_once(self):
        self.assertIsNone(duels.respond(self.duel.pk, self.ana, accept=True))
        self.assertIsNone(duels.respond(self.duel.pk, self.cris, accept=True))
        self.assertIsNotNone(duels.respond(self.duel.pk, self.bia, accept=True))
        self.assertIsNone(duels.respond(self.duel.pk, self.bia, accept=False))

    def test_only_the_challenger_can_cancel(self):
        self.assertIsNone(duels.cancel(self.duel.pk, self.bia))
        self.assertIsNotNone(duels.cancel(self.duel.pk, self.ana))
        self.assertIsNone(duels.respond(self.duel.pk, self.bia, accept=True))


class ScoreTests(TestCase):
    def setUp(self):
        self.ana = make_profile("ana")
        self.bia = make_profile("bia")

    def test_xp_follows_the_study_rules(self):
        log_answer(self.ana, "hard")  # 20
        log_answer(self.ana, "easy")  # 5
        log_answer(self.ana, "hard", is_correct=False)  # 2
        now = timezone.now()
        self.assertEqual(
            duels.xp_between(self.ana.pk, now - timedelta(days=1), now + timedelta(days=1)), 27
        )

    def test_only_answers_inside_the_period_count(self):
        duel = start_duel(self.ana, self.bia)
        log_answer(self.ana, "hard", at=duel.starts_at - timedelta(hours=1))  # antes
        log_answer(self.ana, "easy")  # 5
        log_answer(self.bia, "medium")  # 10
        board = duels.scoreboard(duel, self.ana)
        self.assertEqual((board.my_xp, board.opponent_xp), (5, 10))
        self.assertEqual(board.result, "behind")
        self.assertFalse(board.finished)

    def test_results_after_the_end(self):
        duel = start_duel(self.ana, self.bia)
        now = timezone.now()
        end = now - timedelta(minutes=1)
        Duel.objects.filter(pk=duel.pk).update(starts_at=now - timedelta(days=7), ends_at=end)
        duel.refresh_from_db()
        log_answer(self.ana, "hard", at=now - timedelta(days=1))
        log_answer(self.bia, "easy", at=now - timedelta(days=1))
        log_answer(self.bia, "hard", at=end + timedelta(seconds=30))  # depois do fim: ignorada
        self.assertEqual(duels.scoreboard(duel, self.ana).result, "win")
        self.assertEqual(duels.scoreboard(duel, self.bia).result, "loss")

    def test_draw(self):
        duel = start_duel(self.ana, self.bia)
        log_answer(self.ana, "easy")
        log_answer(self.bia, "easy")
        self.assertEqual(duels.scoreboard(duel, self.ana).result, "tied")


class DuelViewTests(TestCase):
    def setUp(self):
        self.ana = make_profile("ana")
        self.bia = make_profile("bia")
        self.client.force_login(self.ana.user, backend=BACKEND)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("duels")).status_code, 302)

    def test_challenge_flow(self):
        response = self.client.post(reverse("duels"), {"username": "bia", "duration_days": 7})
        self.assertContains(response, "Desafio enviado para bia")
        self.client.force_login(self.bia.user, backend=BACKEND)
        self.assertContains(self.client.get(reverse("duels")), "ana desafiou você")
        duel = Duel.objects.get()
        response = self.client.post(reverse("duel_respond", args=[duel.pk, "aceitar"]))
        self.assertRedirects(response, reverse("duels"))
        self.assertContains(self.client.get(reverse("duels")), "Você × ana")

    def test_unknown_user_shows_an_error(self):
        response = self.client.post(reverse("duels"), {"username": "xx", "duration_days": 7})
        self.assertContains(response, "Não encontramos ninguém")

    def test_invalid_decision_is_404(self):
        duel = duels.challenge(self.bia, "ana", 7)
        response = self.client.post(reverse("duel_respond", args=[duel.pk, "talvez"]))
        self.assertEqual(response.status_code, 404)
