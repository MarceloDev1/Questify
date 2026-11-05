"""Regras de gamificação e repetição espaçada."""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Profile

from .models import Flashcard, StudyLog

XP_BY_DIFFICULTY = {"easy": 5, "medium": 10, "hard": 20}
XP_FOR_WRONG_ANSWER = 2

# Cada acerto consecutivo avança um passo; um erro volta ao início.
REVIEW_INTERVALS_DAYS = [1, 3, 7, 14, 30, 60]
RETRY_AFTER_WRONG_MINUTES = 10


@dataclass(frozen=True)
class AnswerResult:
    is_correct: bool
    xp_gained: int
    leveled_up: bool
    next_review_label: str
    profile: Profile


def next_streak(current, last_studied_on, today):
    if last_studied_on == today:
        return current
    if last_studied_on == today - timedelta(days=1):
        return current + 1
    return 1


def _consecutive_correct(flashcard):
    count = 0
    for is_correct in flashcard.logs.order_by("-created_at", "-id").values_list(
        "is_correct", flat=True
    ):
        if not is_correct:
            break
        count += 1
    return count


@transaction.atomic
def record_answer(profile, flashcard_id, is_correct, response_time_seconds=None):
    """Registra a resposta de um card que esteja na hora de revisar.

    Devolve None se o card não estiver pendente. Assim, um clique duplo não
    registra a resposta duas vezes nem concede XP em dobro.
    """
    now = timezone.now()
    flashcard = (
        Flashcard.objects.select_for_update()
        .filter(pk=flashcard_id, user_id=profile.pk, next_review__lte=now)
        .first()
    )
    if flashcard is None:
        return None

    locked_profile = Profile.objects.select_for_update().get(pk=profile.pk)
    previous_level = locked_profile.level
    locked_profile.streak = next_streak(
        locked_profile.streak, locked_profile.last_studied_on, timezone.localdate(now)
    )
    # Recalculado no próximo acesso, já considerando esta resposta.
    locked_profile.__dict__.pop("last_studied_on", None)

    StudyLog.objects.create(
        user=locked_profile,
        flashcard=flashcard,
        is_correct=is_correct,
        response_time_seconds=response_time_seconds,
        created_at=now,
    )

    if is_correct:
        xp_gained = XP_BY_DIFFICULTY.get(flashcard.difficulty, XP_BY_DIFFICULTY["medium"])
        step = min(_consecutive_correct(flashcard), len(REVIEW_INTERVALS_DAYS)) - 1
        days = REVIEW_INTERVALS_DAYS[step]
        flashcard.next_review = now + timedelta(days=days)
        next_review_label = "1 dia" if days == 1 else f"{days} dias"
    else:
        xp_gained = XP_FOR_WRONG_ANSWER
        flashcard.next_review = now + timedelta(minutes=RETRY_AFTER_WRONG_MINUTES)
        next_review_label = f"{RETRY_AFTER_WRONG_MINUTES} minutos"
    flashcard.save(update_fields=["next_review"])

    locked_profile.xp += xp_gained
    locked_profile.save(update_fields=["xp", "streak"])

    return AnswerResult(
        is_correct=is_correct,
        xp_gained=xp_gained,
        leveled_up=locked_profile.level > previous_level,
        next_review_label=next_review_label,
        profile=locked_profile,
    )


def next_due_card(profile):
    return profile.flashcards.filter(next_review__lte=timezone.now()).order_by("next_review", "id").first()
