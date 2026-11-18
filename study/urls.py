from django.urls import path

from . import views

urlpatterns = [
    path("painel/", views.dashboard, name="dashboard"),
    path("estudar/", views.study, name="study"),
    path("estudar/<int:card_id>/resposta/", views.reveal, name="study_reveal"),
    path("estudar/<int:card_id>/responder/", views.answer, name="study_answer"),
    path("flashcards/", views.flashcards, name="flashcards"),
    path("flashcards/<int:card_id>/excluir/", views.flashcard_delete, name="flashcard_delete"),
    path("duelos/", views.duels_page, name="duels"),
    path("duelos/<int:duel_id>/cancelar/", views.duel_cancel, name="duel_cancel"),
    path("duelos/<int:duel_id>/<str:decision>/", views.duel_respond, name="duel_respond"),
    path("materiais/", views.materials, name="materials"),
    path("materiais/excluir/", views.material_delete, name="material_delete"),
]
