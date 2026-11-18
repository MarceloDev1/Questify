"""Duelos: dois usuários disputam quem ganha mais XP em um período."""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Sum, Value, When
from django.utils import timezone

from accounts.models import Profile

from .models import Duel, StudyLog
from .services import XP_BY_DIFFICULTY, XP_FOR_WRONG_ANSWER

DURATION_CHOICES = [(3, "3 dias"), (7, "7 dias"), (14, "14 dias"), (30, "30 dias")]
MAX_OPEN_DUELS = 5  # pendentes + em andamento por usuário


class DuelError(Exception):
    """A mensagem pode ser exibida diretamente ao usuário."""


def _xp_expression():
    correct = [
        When(is_correct=True, flashcard__difficulty=difficulty, then=Value(xp))
        for difficulty, xp in XP_BY_DIFFICULTY.items()
    ]
    return Sum(
        Case(
            *correct,
            When(is_correct=True, then=Value(XP_BY_DIFFICULTY["medium"])),
            default=Value(XP_FOR_WRONG_ANSWER),
            output_field=IntegerField(),
        )
    )


def xp_between(profile_id, start, end):
    """XP ganho no intervalo, recalculado a partir do histórico de respostas."""
    total = StudyLog.objects.filter(
        user_id=profile_id, created_at__gte=start, created_at__lt=end
    ).aggregate(xp=_xp_expression())["xp"]
    return total or 0


def _open_duels(profile):
    now = timezone.now()
    return Duel.objects.filter(Q(challenger=profile) | Q(opponent=profile)).filter(
        Q(status=Duel.Status.PENDING) | Q(status=Duel.Status.ACTIVE, ends_at__gt=now)
    )


@transaction.atomic
def challenge(challenger, username, duration_days):
    opponent = Profile.objects.filter(username__iexact=username.strip()).first()
    if opponent is None:
        raise DuelError("Não encontramos ninguém com esse nome de usuário.")
    if opponent.pk == challenger.pk:
        raise DuelError("Você não pode desafiar a si mesmo.")
    if duration_days not in dict(DURATION_CHOICES):
        raise DuelError("Duração inválida.")
    if _open_duels(challenger).count() >= MAX_OPEN_DUELS:
        raise DuelError("Você já tem duelos demais em aberto. Conclua ou cancele algum.")
    already = _open_duels(challenger).filter(
        Q(challenger=opponent) | Q(opponent=opponent)
    ).exists()
    if already:
        raise DuelError(f"Você já tem um duelo em aberto com {opponent.username}.")
    return Duel.objects.create(
        challenger=challenger, opponent=opponent, duration_days=duration_days
    )


@transaction.atomic
def respond(duel_id, profile, accept):
    """O desafiado aceita (o relógio começa agora) ou recusa. None se não for possível."""
    duel = (
        Duel.objects.select_for_update()
        .filter(pk=duel_id, opponent=profile, status=Duel.Status.PENDING)
        .first()
    )
    if duel is None:
        return None
    if accept:
        now = timezone.now()
        duel.status = Duel.Status.ACTIVE
        duel.starts_at = now
        duel.ends_at = now + timedelta(days=duel.duration_days)
        duel.save(update_fields=["status", "starts_at", "ends_at"])
    else:
        duel.status = Duel.Status.DECLINED
        duel.save(update_fields=["status"])
    return duel


@transaction.atomic
def cancel(duel_id, profile):
    duel = (
        Duel.objects.select_for_update()
        .filter(pk=duel_id, challenger=profile, status=Duel.Status.PENDING)
        .first()
    )
    if duel is None:
        return None
    duel.status = Duel.Status.CANCELLED
    duel.save(update_fields=["status"])
    return duel


@dataclass(frozen=True)
class Scoreboard:
    duel: Duel
    opponent: Profile
    my_xp: int
    opponent_xp: int
    finished: bool

    @property
    def result(self):
        """'win', 'loss' ou 'draw' se encerrado; 'lead', 'behind' ou 'tied' em andamento."""
        if self.my_xp == self.opponent_xp:
            return "draw" if self.finished else "tied"
        ahead = self.my_xp > self.opponent_xp
        if self.finished:
            return "win" if ahead else "loss"
        return "lead" if ahead else "behind"

    @property
    def my_share(self):
        total = self.my_xp + self.opponent_xp
        return round(self.my_xp * 100 / total) if total else 50


def scoreboard(duel, me):
    opponent = duel.other(me)
    end = min(duel.ends_at, timezone.now())
    return Scoreboard(
        duel=duel,
        opponent=opponent,
        my_xp=xp_between(me.pk, duel.starts_at, end),
        opponent_xp=xp_between(opponent.pk, duel.starts_at, end),
        finished=duel.is_finished,
    )


def duels_overview(profile):
    """Convites recebidos e enviados, duelos em andamento e os últimos encerrados."""
    now = timezone.now()
    mine = Duel.objects.filter(Q(challenger=profile) | Q(opponent=profile)).select_related(
        "challenger", "opponent"
    )
    active = mine.filter(status=Duel.Status.ACTIVE, ends_at__gt=now).order_by("ends_at")
    finished = mine.filter(status=Duel.Status.ACTIVE, ends_at__lte=now).order_by("-ends_at")[:10]
    return {
        "invites": mine.filter(status=Duel.Status.PENDING, opponent=profile).order_by("-id"),
        "sent": mine.filter(status=Duel.Status.PENDING, challenger=profile).order_by("-id"),
        "active": [scoreboard(d, profile) for d in active],
        "finished": [scoreboard(d, profile) for d in finished],
    }
