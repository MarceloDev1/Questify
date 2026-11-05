from datetime import timedelta
from math import isqrt

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

XP_PER_LEVEL_UNIT = 100


class User(AbstractBaseUser):
    """Usuário de sessão do Django. O `id` é o mesmo de auth.users no Supabase.

    A senha é verificada pelo Supabase Auth e nunca fica guardada aqui.
    """

    id = models.UUIDField(primary_key=True, editable=False)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)

    objects = BaseUserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"


class Profile(models.Model):
    # A FK real no banco aponta para auth.users; ver supabase/schema.sql.
    user = models.OneToOneField(
        User,
        primary_key=True,
        db_column="id",
        db_constraint=False,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    username = models.TextField(unique=True)
    xp = models.IntegerField(default=0)
    streak = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = "profiles"

    @property
    def level(self):
        return isqrt(self.xp // XP_PER_LEVEL_UNIT) + 1

    @property
    def next_level_xp(self):
        return XP_PER_LEVEL_UNIT * self.level**2

    @property
    def level_progress(self):
        """Percentual já percorrido dentro do nível atual."""
        floor = XP_PER_LEVEL_UNIT * (self.level - 1) ** 2
        return (self.xp - floor) * 100 // (self.next_level_xp - floor)

    @cached_property
    def last_studied_on(self):
        last = (
            self.study_logs.order_by("-created_at").values_list("created_at", flat=True).first()
        )
        return timezone.localdate(last) if last else None

    @property
    def current_streak(self):
        """A coluna só muda ao responder; quem parou de estudar exibe 0."""
        last = self.last_studied_on
        if last is None or last < timezone.localdate() - timedelta(days=1):
            return 0
        return self.streak
