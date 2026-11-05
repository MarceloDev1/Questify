from django.urls import path

from . import views

urlpatterns = [
    path("painel/", views.dashboard, name="dashboard"),
    path("estudar/", views.study, name="study"),
    path("estudar/<int:card_id>/resposta/", views.reveal, name="study_reveal"),
    path("estudar/<int:card_id>/responder/", views.answer, name="study_answer"),
    path("flashcards/", views.flashcards, name="flashcards"),
    path("flashcards/<int:card_id>/excluir/", views.flashcard_delete, name="flashcard_delete"),
    path("materiais/", views.materials, name="materials"),
    path("materiais/excluir/", views.material_delete, name="material_delete"),
]
