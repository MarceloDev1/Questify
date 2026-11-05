# Questify

Plataforma de estudos gamificada: envie seus materiais, gere flashcards com RAG e ganhe XP revisando.

Feita com Django, HTMX, Chart.js, Supabase (Postgres, Auth e pgvector) e OpenAI. O RAG é escrito em Python puro, sem LangChain.

## Como rodar

Você precisa de Python 3.11+, um projeto no [Supabase](https://supabase.com) e uma chave da OpenAI.

1. No **SQL Editor** do Supabase, execute [`supabase/schema.sql`](supabase/schema.sql).

2. Instale as dependências:

   ```bash
   py -3.11 -m venv .venv
   ```

   ```bash
   .venv\Scripts\activate
   ```

   ```bash
   pip install -r requirements.txt
   ```

3. Copie `.env.example` para `.env` e preencha os valores:

   ```bash
   copy .env.example .env
   ```

4. Crie as tabelas do Django e suba o servidor:

   ```bash
   python manage.py migrate
   ```

   ```bash
   python manage.py runserver
   ```

5. Acesse http://localhost:8000, crie uma conta, envie um material em **Materiais** e gere cards em **Flashcards**.

Se o projeto Supabase exigir confirmação de e-mail, que é o padrão, confirme pelo link recebido antes de entrar.

## Como funciona

**Banco de dados.** `supabase/schema.sql` é a fonte da verdade das tabelas `profiles`, `documents_rag`, `flashcards` e `study_logs`. No Django, esses modelos são `managed = False`: as migrations não alteram essas tabelas e só criam as do próprio Django (usuários e sessões).

**Autenticação.** O Supabase Auth valida a senha. Depois disso, o Django cria um usuário local com o mesmo UUID de `auth.users` e a sessão passa a ser do Django. Nenhuma senha é guardada no Django.

**RAG** (`study/rag.py`):

1. Extrai o texto de PDF, TXT ou Markdown.
2. Divide o texto em trechos de até 1.000 caracteres, com 150 de sobreposição.
3. Gera os embeddings com `text-embedding-3-small` e salva em `documents_rag`.
4. Busca os trechos do usuário mais próximos do tema, por distância de cosseno.
5. Envia esses trechos ao modelo, que devolve os flashcards em JSON.

**Gamificação** (`study/services.py`):

| Regra | Valor |
|---|---|
| XP por acerto | Fácil 5, média 10, difícil 20 |
| XP por erro | 2 |
| Nível | Nível 2 com 100 XP, nível 3 com 400, nível 4 com 900 |
| Sequência | Sobe no primeiro estudo do dia e zera se você pular um dia |
| Próxima revisão após acerto | 1, 3, 7, 14, 30 e 60 dias, conforme os acertos seguidos |
| Próxima revisão após erro | 10 minutos, e os acertos seguidos voltam a zero |

## Segurança no Supabase

O Supabase expõe o schema `public` pela API REST usando a chave anon. Por isso, o RLS é ligado sem policies em todas as tabelas: as de domínio pelo `schema.sql` e as do Django depois de cada `migrate`. Assim, a API REST não acessa esses dados, e o Django continua acessando porque conecta como dono das tabelas.

Se um dia o front-end for acessar o Supabase diretamente, será preciso criar policies.

## Testes

Os testes usam Postgres de verdade, porque dependem de pgvector e do `schema.sql`. Chamadas ao Supabase Auth e à OpenAI são simuladas.

```bash
docker compose up -d
```

No PowerShell:

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@localhost:5433/postgres"; python manage.py test
```
