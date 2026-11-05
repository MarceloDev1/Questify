"""RAG sem frameworks: extração de texto, chunking, indexação, busca e geração."""

import re
from pathlib import Path

from django.db import transaction
from pgvector.django import CosineDistance
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from . import ai
from .models import DocumentChunk, Flashcard

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MAX_MATERIAL_CHARS = 200_000
MIN_RETRIEVED_CHUNKS = 6
MAX_RETRIEVED_CHUNKS = 12

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


class MaterialError(Exception):
    """A mensagem pode ser exibida diretamente ao usuário."""


def extract_text(uploaded_file):
    extension = Path(uploaded_file.name).suffix.lower()
    if extension == ".pdf":
        try:
            pages = PdfReader(uploaded_file).pages
            return "\n\n".join(page.extract_text() or "" for page in pages)
        except (PyPdfError, ValueError, KeyError, TypeError) as exc:
            raise MaterialError("Não foi possível ler esse PDF.") from exc
    raw = uploaded_file.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def normalize_text(text):
    # O PostgreSQL não aceita NUL em text, e alguns PDFs produzem esse caractere.
    text = text.replace("\x00", "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Janela deslizante que prefere cortar em parágrafo, frase ou palavra."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            for separator in ("\n\n", ". ", "\n", " "):
                cut = text.rfind(separator, start + size // 2, end)
                if cut != -1:
                    end = cut + len(separator)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
        # Evita começar o próximo trecho no meio de uma palavra.
        space = text.find(" ", start, end)
        if space != -1:
            start = space + 1
    return chunks


def ingest_document(profile, title, text):
    """Indexa o material e devolve a quantidade de trechos criados."""
    text = normalize_text(text)
    if not text:
        raise MaterialError("Não encontramos texto nesse material. PDFs escaneados não são suportados.")
    if len(text) > MAX_MATERIAL_CHARS:
        raise MaterialError(
            f"Material muito grande: o limite é de {MAX_MATERIAL_CHARS:,} caracteres.".replace(",", ".")
        )
    chunks = chunk_text(text)
    embeddings = ai.embed_texts(chunks)
    with transaction.atomic():
        DocumentChunk.objects.bulk_create(
            DocumentChunk(user=profile, title=title, content=content, embedding=embedding)
            for content, embedding in zip(chunks, embeddings, strict=True)
        )
    return len(chunks)


def retrieve(profile, query, k=MIN_RETRIEVED_CHUNKS, title=None):
    """Busca os trechos do próprio usuário mais próximos da consulta."""
    chunks = DocumentChunk.objects.filter(user=profile)
    if title:
        chunks = chunks.filter(title=title)
    if not chunks.exists():
        return []
    query_embedding = ai.embed_texts([query])[0]
    return list(
        chunks.annotate(distance=CosineDistance("embedding", query_embedding)).order_by("distance")[:k]
    )


def generate_flashcards(profile, topic, count, title=None):
    """Recupera contexto, gera os cards e salva. Devolve os cards criados."""
    k = min(max(count, MIN_RETRIEVED_CHUNKS), MAX_RETRIEVED_CHUNKS)
    chunks = retrieve(profile, topic, k=k, title=title)
    if not chunks:
        raise MaterialError("Envie um material antes de gerar flashcards.")

    items = ai.generate_flashcard_items(topic, count, chunks)
    existing = {q.casefold() for q in profile.flashcards.values_list("question", flat=True)}
    valid_difficulties = Flashcard.Difficulty.values
    cards = []
    for item in items:
        if item["question"].casefold() in existing:
            continue
        existing.add(item["question"].casefold())
        difficulty = item["difficulty"]
        cards.append(
            Flashcard(
                user=profile,
                question=item["question"],
                answer=item["answer"],
                topic=topic,
                difficulty=(
                    difficulty if difficulty in valid_difficulties else Flashcard.Difficulty.MEDIUM
                ),
            )
        )
    if not cards:
        raise MaterialError(
            "Não encontramos conteúdo novo sobre esse tema nos seus materiais. Tente outro tema."
        )
    return Flashcard.objects.bulk_create(cards)
