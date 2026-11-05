"""Ponto de entrada da Vercel: a função serverless Python usa o objeto `app` (WSGI)."""

from questify.wsgi import application

app = application
