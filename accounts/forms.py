from django import forms

from .models import Profile


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True})
    )
    password = forms.CharField(
        label="Senha", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )


class SignupForm(forms.Form):
    username = forms.RegexField(
        label="Nome de usuário",
        regex=r"^[\w.-]{3,30}$",
        help_text="De 3 a 30 letras, números, pontos, hífens ou sublinhados.",
        error_messages={"invalid": "Use de 3 a 30 letras, números, pontos, hífens ou sublinhados."},
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    email = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(
        label="Senha",
        min_length=8,
        help_text="Pelo menos 8 caracteres.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"]
        if Profile.objects.filter(username=username).exists():
            raise forms.ValidationError("Esse nome de usuário já está em uso.")
        return username
