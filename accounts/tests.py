from unittest import mock
from uuid import uuid4

import requests
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Profile, User
from .supabase_auth import SupabaseUser, sync_local_user

SUPABASE = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_ANON_KEY": "anon"}


def insert_auth_user(user_id):
    """O banco de teste simula auth.users; a FK de profiles aponta para lá."""
    with connection.cursor() as cursor:
        cursor.execute("insert into auth.users (id) values (%s)", [str(user_id)])


def make_profile(username="ana", xp=0, streak=0):
    user_id = uuid4()
    insert_auth_user(user_id)
    user = User.objects.create(id=user_id, email=f"{username}@example.com")
    user.set_unusable_password()
    user.save()
    return Profile.objects.create(user=user, username=username, xp=xp, streak=streak)


def fake_response(status, body):
    response = requests.Response()
    response.status_code = status
    response.json = lambda: body
    return response


@override_settings(**SUPABASE)
class LoginTests(TestCase):
    def _login(self, **extra):
        data = {"email": "ana@example.com", "password": "senha-segura"}
        return self.client.post(reverse("login"), data | extra)

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_success_creates_local_user_and_profile(self, post):
        user_id = uuid4()
        insert_auth_user(user_id)
        post.return_value = fake_response(
            200,
            {
                "access_token": "jwt",
                "user": {
                    "id": str(user_id),
                    "email": "ana@example.com",
                    "user_metadata": {"username": "ana"},
                },
            },
        )

        response = self._login()

        self.assertRedirects(response, reverse("dashboard"))
        profile = Profile.objects.get(pk=user_id)
        self.assertEqual(profile.username, "ana")
        self.assertFalse(profile.user.has_usable_password())
        self.assertEqual(int(self.client.session["_auth_user_id"].replace("-", ""), 16), user_id.int)

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_login_does_not_store_the_password(self, post):
        user_id = uuid4()
        insert_auth_user(user_id)
        post.return_value = fake_response(
            200, {"user": {"id": str(user_id), "email": "ana@example.com"}}
        )
        self._login()
        self.assertFalse(User.objects.get(pk=user_id).has_usable_password())

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_invalid_credentials(self, post):
        post.return_value = fake_response(400, {"error_code": "invalid_credentials"})
        response = self._login()
        self.assertContains(response, "E-mail ou senha incorretos.")
        self.assertNotIn("_auth_user_id", self.client.session)

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_email_not_confirmed(self, post):
        post.return_value = fake_response(400, {"error_code": "email_not_confirmed"})
        self.assertContains(self._login(), "Confirme seu e-mail")

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_network_failure_shows_generic_error(self, post):
        post.side_effect = requests.ConnectionError()
        self.assertContains(self._login(), "Não foi possível falar com o serviço")

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_next_rejects_external_url(self, post):
        user_id = uuid4()
        insert_auth_user(user_id)
        post.return_value = fake_response(
            200, {"user": {"id": str(user_id), "email": "ana@example.com"}}
        )
        response = self._login(next="https://malicioso.example/")
        self.assertRedirects(response, reverse("dashboard"))


@override_settings(**SUPABASE)
class SignupTests(TestCase):
    def _signup(self, username="novo_user"):
        return self.client.post(
            reverse("signup"),
            {"username": username, "email": "novo@example.com", "password": "senha-segura"},
        )

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_with_email_confirmation_shows_instructions_and_does_not_log_in(self, post):
        post.return_value = fake_response(200, {"id": str(uuid4()), "email": "novo@example.com"})
        response = self._signup()
        self.assertContains(response, "Confirme seu e-mail")
        self.assertNotIn("_auth_user_id", self.client.session)

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_without_email_confirmation_logs_in(self, post):
        user_id = uuid4()
        insert_auth_user(user_id)
        post.return_value = fake_response(
            200,
            {
                "access_token": "jwt",
                "user": {
                    "id": str(user_id),
                    "email": "novo@example.com",
                    "user_metadata": {"username": "novo_user"},
                },
            },
        )
        self.assertRedirects(self._signup(), reverse("dashboard"))
        self.assertEqual(Profile.objects.get(pk=user_id).username, "novo_user")

    @mock.patch("accounts.supabase_auth.requests.post")
    def test_taken_username_never_reaches_supabase(self, post):
        make_profile("ocupado")
        self.assertContains(self._signup("ocupado"), "já está em uso")
        post.assert_not_called()


class SyncLocalUserTests(TestCase):
    def test_username_collision_gets_suffix(self):
        make_profile("ana")
        user_id = uuid4()
        insert_auth_user(user_id)
        user = sync_local_user(SupabaseUser(user_id, "ana2@example.com", "ana"))
        self.assertEqual(user.profile.username, "ana2")

    def test_recreated_account_with_same_email_replaces_stale_user(self):
        old = make_profile("ana")
        new_id = uuid4()
        insert_auth_user(new_id)
        user = sync_local_user(SupabaseUser(new_id, old.user.email, "ana"))
        self.assertEqual(user.pk, new_id)
        self.assertEqual(User.objects.filter(email=user.email).count(), 1)

    def test_second_login_keeps_progress(self):
        profile = make_profile("ana", xp=50)
        sync_local_user(SupabaseUser(profile.pk, "novo-email@example.com", None))
        profile.refresh_from_db()
        self.assertEqual(profile.xp, 50)
        self.assertEqual(profile.user.email, "novo-email@example.com")


class MiddlewareTests(TestCase):
    def test_session_ends_when_profile_was_deleted_in_supabase(self):
        profile = make_profile()
        self.client.force_login(profile.user, backend="django.contrib.auth.backends.ModelBackend")
        with connection.cursor() as cursor:
            cursor.execute("delete from profiles where id = %s", [str(profile.pk)])
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_htmx_request_with_expired_session_redirects_whole_page(self):
        response = self.client.get(reverse("study"), headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 204)
        self.assertIn(reverse("login"), response["HX-Redirect"])


class LevelTests(TestCase):
    def test_level_thresholds_and_progress(self):
        cases = [(0, 1, 0), (99, 1, 99), (100, 2, 0), (250, 2, 50), (400, 3, 0)]
        for xp, level, progress in cases:
            with self.subTest(xp=xp):
                profile = Profile(xp=xp)
                self.assertEqual(profile.level, level)
                self.assertEqual(profile.level_progress, progress)


class RowLevelSecurityTests(TestCase):
    def test_every_public_table_has_rls_enabled(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "select tablename from pg_tables where schemaname = 'public' and not rowsecurity"
            )
            self.assertEqual(cursor.fetchall(), [])
