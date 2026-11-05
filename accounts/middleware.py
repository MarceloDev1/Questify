from django.contrib.auth import logout
from django.http import HttpResponse

from .models import Profile


class ProfileMiddleware:
    """Expõe request.profile e encerra a sessão de contas apagadas no Supabase."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.profile = None
        if request.user.is_authenticated:
            request.profile = Profile.objects.filter(pk=request.user.pk).first()
            if request.profile is None:
                logout(request)
        return self.get_response(request)


class HtmxRedirectMiddleware:
    """Faz o navegador seguir redirects de HTMX, como o de sessão expirada.

    Sem isso, o HTMX seguiria o 302 e colocaria a página de login dentro do alvo.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.headers.get("HX-Request") and response.status_code == 302:
            return HttpResponse(status=204, headers={"HX-Redirect": response["Location"]})
        return response
