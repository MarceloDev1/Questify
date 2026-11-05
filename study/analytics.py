"""Dados dos gráficos de desempenho."""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

HISTORY_DAYS = 30
NO_TOPIC_LABEL = "Sem tópico"
_ANSWER_COUNTS = {
    "correct": Count("id", filter=Q(is_correct=True)),
    "wrong": Count("id", filter=Q(is_correct=False)),
}


def _topic_label(topic):
    return topic or NO_TOPIC_LABEL


def summary(profile):
    totals = profile.study_logs.aggregate(
        **_ANSWER_COUNTS, average_seconds=Avg("response_time_seconds")
    )
    answered = totals["correct"] + totals["wrong"]
    average = totals["average_seconds"]
    return {
        "answered": answered,
        "accuracy": round(totals["correct"] * 100 / answered) if answered else None,
        "average_seconds": round(average) if average is not None else None,
    }


def performance_by_topic(profile):
    rows = (
        profile.study_logs.values("flashcard__topic").annotate(**_ANSWER_COUNTS).order_by()
    )
    topics = [
        {
            "topic": _topic_label(row["flashcard__topic"]),
            "correct": row["correct"],
            "wrong": row["wrong"],
            "total": row["correct"] + row["wrong"],
            "accuracy": round(row["correct"] * 100 / (row["correct"] + row["wrong"])),
        }
        for row in rows
    ]
    return sorted(topics, key=lambda item: (-item["total"], item["topic"]))


def daily_history(profile, days=HISTORY_DAYS):
    """Acertos e erros por dia, no total e por tópico, com os dias vazios zerados."""
    today = timezone.localdate()
    dates = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    since = timezone.make_aware(datetime.combine(dates[0], time.min))
    rows = (
        profile.study_logs.filter(created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day", "flashcard__topic")
        .annotate(**_ANSWER_COUNTS)
        .order_by()
    )

    index = {day: position for position, day in enumerate(dates)}
    empty = lambda: {"correct": [0] * days, "wrong": [0] * days}  # noqa: E731
    overall = empty()
    by_topic = defaultdict(empty)
    for row in rows:
        position = index.get(row["day"])
        if position is None:
            continue
        topic = by_topic[_topic_label(row["flashcard__topic"])]
        for key in ("correct", "wrong"):
            overall[key][position] += row[key]
            topic[key][position] += row[key]

    return {
        "days": [day.isoformat() for day in dates],
        "overall": overall,
        "byTopic": dict(sorted(by_topic.items())),
    }
