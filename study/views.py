import time

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import analytics, rag, services
from .ai import AIServiceError
from .forms import GenerateFlashcardsForm, MaterialForm
from .models import Flashcard

MAX_RESPONSE_SECONDS = 3600
DECK_PAGE_SIZE = 100


def _render_page_or_panel(request, page, panel, context):
    """Requisições HTMX recebem só o painel; as demais, a página inteira."""
    return render(request, panel if request.headers.get("HX-Request") else page, context)


@login_required
@require_GET
def dashboard(request):
    profile = request.profile
    by_topic = analytics.performance_by_topic(profile)
    return render(
        request,
        "study/dashboard.html",
        {
            "summary": analytics.summary(profile),
            "by_topic": by_topic,
            "chart_data": {"byTopic": by_topic, "history": analytics.daily_history(profile)},
            "due_count": profile.flashcards.filter(next_review__lte=timezone.now()).count(),
        },
    )


# Estudo


def _card_context(profile):
    card = services.next_due_card(profile)
    return {
        "card": card,
        "started_at": int(time.time()),
        "due_count": profile.flashcards.filter(next_review__lte=timezone.now()).count(),
        "next_upcoming": (
            None
            if card
            else profile.flashcards.order_by("next_review").values_list("next_review", flat=True).first()
        ),
    }


@login_required
@require_GET
def study(request):
    return render(request, "study/study.html", _card_context(request.profile))


@login_required
@require_GET
def reveal(request, card_id):
    card = get_object_or_404(Flashcard, pk=card_id, user=request.profile)
    try:
        elapsed = int(time.time()) - int(request.GET.get("inicio", ""))
    except ValueError:
        elapsed = None
    return render(request, "study/_reveal.html", {"card": card, "response_time": elapsed})


def _clean_response_time(raw):
    try:
        return max(0, min(int(raw), MAX_RESPONSE_SECONDS))
    except (TypeError, ValueError):
        return None


@login_required
@require_POST
def answer(request, card_id):
    get_object_or_404(Flashcard, pk=card_id, user=request.profile)
    choice = request.POST.get("is_correct")
    if choice not in ("0", "1"):
        return HttpResponseBadRequest("Resposta inválida.")

    result = services.record_answer(
        request.profile,
        card_id,
        is_correct=choice == "1",
        response_time_seconds=_clean_response_time(request.POST.get("response_time")),
    )
    if result:
        request.profile = result.profile
    context = _card_context(request.profile)
    context.update(result=result, oob=True)
    return render(request, "study/_card.html", context)


# Flashcards


def _deck_context(profile, form=None, notice=None):
    cards = profile.flashcards.order_by("-id")
    return {
        "form": form or GenerateFlashcardsForm(profile, initial={"count": 5}),
        "cards": cards[:DECK_PAGE_SIZE],
        "total_cards": cards.count(),
        "page_size": DECK_PAGE_SIZE,
        "notice": notice,
        "has_materials": profile.chunks.exists(),
    }


@login_required
@require_http_methods(["GET", "POST"])
def flashcards(request):
    profile = request.profile
    form = None
    notice = None
    if request.method == "POST":
        form = GenerateFlashcardsForm(profile, request.POST)
        if form.is_valid():
            try:
                created = rag.generate_flashcards(
                    profile,
                    form.cleaned_data["topic"],
                    form.cleaned_data["count"],
                    title=form.cleaned_data["material"] or None,
                )
            except (AIServiceError, rag.MaterialError) as exc:
                form.add_error(None, str(exc))
            else:
                form = None
                notice = (
                    "1 flashcard criado." if len(created) == 1 else f"{len(created)} flashcards criados."
                )
    return _render_page_or_panel(
        request,
        "study/flashcards.html",
        "study/_flashcards_panel.html",
        _deck_context(profile, form, notice),
    )


@login_required
@require_POST
def flashcard_delete(request, card_id):
    get_object_or_404(Flashcard, pk=card_id, user=request.profile).delete()
    return render(request, "study/_flashcards_panel.html", _deck_context(request.profile))


# Materiais


def _materials_context(profile, form=None, notice=None):
    return {
        "form": form or MaterialForm(profile),
        "notice": notice,
        "materials": (
            profile.chunks.values("title").annotate(chunk_count=Count("id")).order_by("title")
        ),
    }


@login_required
@require_http_methods(["GET", "POST"])
def materials(request):
    profile = request.profile
    form = None
    notice = None
    if request.method == "POST":
        form = MaterialForm(profile, request.POST, request.FILES)
        if form.is_valid():
            uploaded = form.cleaned_data["file"]
            try:
                text = rag.extract_text(uploaded) if uploaded else form.cleaned_data["text"]
                count = rag.ingest_document(profile, form.cleaned_data["title"], text)
            except (AIServiceError, rag.MaterialError) as exc:
                form.add_error(None, str(exc))
            else:
                form = None
                notice = f"Material indexado em {count} {'trecho' if count == 1 else 'trechos'}."
    return _render_page_or_panel(
        request,
        "study/materials.html",
        "study/_materials_panel.html",
        _materials_context(profile, form, notice),
    )


@login_required
@require_POST
def material_delete(request):
    request.profile.chunks.filter(title=request.POST.get("title", "")).delete()
    return render(request, "study/_materials_panel.html", _materials_context(request.profile))
