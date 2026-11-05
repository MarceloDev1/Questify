"""Tabelas de domínio. O schema é definido em supabase/schema.sql, não por migrations."""

from django.db import models
from django.utils import timezone
from pgvector.django import VectorField

from accounts.models import Profile

EMBEDDING_DIMENSIONS = 1536


class DocumentChunk(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        Profile, db_column="user_id", on_delete=models.CASCADE, related_name="chunks"
    )
    title = models.TextField()
    content = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)

    class Meta:
        managed = False
        db_table = "documents_rag"


class Flashcard(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "easy", "Fácil"
        MEDIUM = "medium", "Média"
        HARD = "hard", "Difícil"

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        Profile, db_column="user_id", on_delete=models.CASCADE, related_name="flashcards"
    )
    question = models.TextField()
    answer = models.TextField()
    topic = models.TextField(null=True, blank=True)
    difficulty = models.TextField(choices=Difficulty.choices, default=Difficulty.MEDIUM)
    next_review = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = "flashcards"

    @property
    def is_due(self):
        return self.next_review <= timezone.now()


class StudyLog(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        Profile, db_column="user_id", on_delete=models.CASCADE, related_name="study_logs"
    )
    flashcard = models.ForeignKey(
        Flashcard, db_column="flashcard_id", on_delete=models.CASCADE, related_name="logs"
    )
    is_correct = models.BooleanField()
    response_time_seconds = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = "study_logs"
