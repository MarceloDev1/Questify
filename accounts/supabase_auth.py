"""Cliente mínimo da API REST do Supabase Auth."""

import logging
import re
from dataclasses import dataclass
from uuid import UUID

import requests
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction

from .models import Profile, User

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10

ERROR_MESSAGES = {
    "invalid_credentials": "E-mail ou senha incorretos.",
    "invalid_grant": "E-mail ou senha incorretos.",
    "email_not_confirmed": "Confirme seu e-mail antes de entrar. Verifique sua caixa de entrada.",
    "user_already_exists": "Já existe uma conta com este e-mail.",
    "email_exists": "Já existe uma conta com este e-mail.",
    "weak_password": "Essa senha é fraca demais. Escolha uma senha mais forte.",
    "email_address_invalid": "Esse endereço de e-mail não é aceito.",
    "signup_disabled": "O cadastro de novos usuários está desativado.",
    "over_email_send_rate_limit": "Muitos e-mails enviados. Aguarde alguns minutos.",
    "over_request_rate_limit": "Muitas tentativas. Aguarde alguns minutos.",
}
GENERIC_ERROR = "Não foi possível falar com o serviço de autenticação. Tente novamente."


class SupabaseAuthError(Exception):
    """A mensagem pode ser exibida diretamente ao usuário."""


@dataclass(frozen=True)
class SupabaseUser:
    id: UUID
    email: str
    username: str | None


@dataclass(frozen=True)
class SignUpResult:
    user: SupabaseUser
    has_session: bool  # False quando o projeto exige confirmação de e-mail


def _post(path, payload):
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        logger.error("SUPABASE_URL ou SUPABASE_ANON_KEY não configurados.")
        raise SupabaseAuthError(GENERIC_ERROR)
    try:
        response = requests.post(
            f"{settings.SUPABASE_URL}/auth/v1/{path}",
            json=payload,
            headers={"apikey": settings.SUPABASE_ANON_KEY},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("Falha de rede no Supabase Auth: %s", type(exc).__name__)
        raise SupabaseAuthError(GENERIC_ERROR) from exc

    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.ok:
        return body

    code = body.get("error_code") or body.get("error")
    if code not in ERROR_MESSAGES:
        logger.warning("Erro do Supabase Auth: status=%s code=%s", response.status_code, code)
    raise SupabaseAuthError(ERROR_MESSAGES.get(code, GENERIC_ERROR))


def _parse_user(data):
    metadata = data.get("user_metadata") or {}
    return SupabaseUser(id=UUID(data["id"]), email=data["email"], username=metadata.get("username"))


def sign_in(email, password):
    body = _post("token?grant_type=password", {"email": email, "password": password})
    return _parse_user(body["user"])


def sign_up(email, password, username):
    body = _post(
        "signup",
        {"email": email, "password": password, "data": {"username": username}},
    )
    # Com confirmação de e-mail ativa, a resposta é o próprio usuário, sem sessão.
    return SignUpResult(
        user=_parse_user(body.get("user") or body),
        has_session="access_token" in body,
    )


def _available_username(supabase_user):
    base = supabase_user.username or supabase_user.email.split("@")[0]
    base = re.sub(r"[^\w.-]", "", base)[:30] or "estudante"
    candidate = base
    suffix = 1
    # Só é reservado no primeiro login; outra pessoa pode ter pego o nome antes.
    while Profile.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


@transaction.atomic
def sync_local_user(supabase_user):
    """Garante o usuário de sessão e o perfil correspondentes ao do Supabase."""
    # Conta recriada no Supabase: mesmo e-mail, novo id.
    User.objects.filter(email=supabase_user.email).exclude(id=supabase_user.id).delete()
    user, _ = User.objects.update_or_create(
        id=supabase_user.id,
        defaults={"email": supabase_user.email},
        create_defaults={"email": supabase_user.email, "password": make_password(None)},
    )
    if not Profile.objects.filter(pk=user.pk).exists():
        Profile.objects.create(user=user, username=_available_username(supabase_user))
    return user
