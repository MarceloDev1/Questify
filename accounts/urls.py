from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("entrar/", views.login_view, name="login"),
    path("cadastro/", views.signup_view, name="signup"),
    path("sair/", views.logout_view, name="logout"),
]
