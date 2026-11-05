from pathlib import Path

from django import forms

from .rag import ALLOWED_EXTENSIONS

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class MaterialForm(forms.Form):
    title = forms.CharField(label="Título", max_length=200)
    file = forms.FileField(
        label="Arquivo",
        required=False,
        help_text="PDF com texto, TXT ou Markdown, até 5 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(sorted(ALLOWED_EXTENSIONS))}),
    )
    text = forms.CharField(
        label="Ou cole o texto",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )

    def __init__(self, profile, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if self.profile.chunks.filter(title=title).exists():
            raise forms.ValidationError("Você já tem um material com esse título.")
        return title

    def clean_file(self):
        uploaded = self.cleaned_data.get("file")
        if uploaded:
            if Path(uploaded.name).suffix.lower() not in ALLOWED_EXTENSIONS:
                raise forms.ValidationError("Envie um arquivo PDF, TXT ou Markdown.")
            if uploaded.size > MAX_UPLOAD_BYTES:
                raise forms.ValidationError("O arquivo deve ter no máximo 5 MB.")
        return uploaded

    def clean(self):
        cleaned = super().clean()
        has_file = bool(cleaned.get("file"))
        has_text = bool((cleaned.get("text") or "").strip())
        if "file" not in self.errors:
            if has_file and has_text:
                raise forms.ValidationError("Envie um arquivo ou cole um texto, não os dois.")
            if not has_file and not has_text:
                raise forms.ValidationError("Envie um arquivo ou cole um texto.")
        return cleaned


class GenerateFlashcardsForm(forms.Form):
    topic = forms.CharField(
        label="Tema",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: fotossíntese"}),
    )
    material = forms.ChoiceField(label="Buscar em", required=False)
    count = forms.IntegerField(label="Quantidade", min_value=1, max_value=20, initial=5)

    def __init__(self, profile, *args, **kwargs):
        super().__init__(*args, **kwargs)
        titles = profile.chunks.order_by("title").values_list("title", flat=True).distinct()
        self.fields["material"].choices = [("", "Todos os materiais")] + [(t, t) for t in titles]

    def clean_topic(self):
        return self.cleaned_data["topic"].strip()
