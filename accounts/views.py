from django.conf import settings
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import LoginForm, SignupForm
from .supabase_auth import SupabaseAuthError, sign_in, sign_up, sync_local_user

SESSION_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _redirect_after_login(request):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect(resolve_url(settings.LOGIN_REDIRECT_URL))


def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            supabase_user = sign_in(form.cleaned_data["email"], form.cleaned_data["password"])
        except SupabaseAuthError as exc:
            form.add_error(None, str(exc))
        else:
            login(request, sync_local_user(supabase_user), backend=SESSION_BACKEND)
            return _redirect_after_login(request)
    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.POST.get("next") or request.GET.get("next", "")},
    )


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            result = sign_up(
                form.cleaned_data["email"],
                form.cleaned_data["password"],
                form.cleaned_data["username"],
            )
        except SupabaseAuthError as exc:
            form.add_error(None, str(exc))
        else:
            if result.has_session:
                login(request, sync_local_user(result.user), backend=SESSION_BACKEND)
                return redirect(settings.LOGIN_REDIRECT_URL)
            return render(
                request, "accounts/confirm_email.html", {"email": form.cleaned_data["email"]}
            )
    return render(request, "accounts/signup.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)
