-- Execute no SQL Editor do Supabase ANTES de `python manage.py migrate`.

-- Habilitar extensão para vetores
create extension if not exists vector;

-- Tabela de Perfis de Usuário (vinculada ao auth.users do Supabase)
create table profiles (
    id uuid references auth.users on delete cascade primary key,
    username text unique,
    xp int default 0,
    streak int default 0,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Tabela de Documentos do RAG (Chunks e Embeddings)
create table documents_rag (
    id serial primary key,
    user_id uuid references profiles(id) on delete cascade,
    title text,
    content text not null,
    embedding vector(1536) -- text-embedding-3-small
);

-- Tabela de Flashcards
create table flashcards (
    id serial primary key,
    user_id uuid references profiles(id) on delete cascade,
    question text not null,
    answer text not null,
    topic text,
    difficulty text default 'medium',
    next_review timestamp with time zone default now()
);

-- Histórico de Respostas (Para alimentar os gráficos de desempenho)
create table study_logs (
    id serial primary key,
    user_id uuid references profiles(id) on delete cascade,
    flashcard_id int references flashcards(id) on delete cascade,
    is_correct boolean not null,
    response_time_seconds int,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Índices. A busca vetorial é sempre filtrada por usuário, então o índice em
-- user_id com varredura exata é mais adequado que HNSW: um índice aproximado
-- filtra depois de buscar e pode devolver poucos trechos de cada usuário.
create index documents_rag_user_title_idx on documents_rag (user_id, title);
create index flashcards_user_next_review_idx on flashcards (user_id, next_review);
create index study_logs_user_created_idx on study_logs (user_id, created_at);
create index study_logs_flashcard_created_idx on study_logs (flashcard_id, created_at);

-- O Supabase expõe o schema public pela API REST usando a chave anon. Com RLS
-- ligado e sem policies, essa API não acessa nada; o Django continua acessando
-- porque conecta como dono das tabelas.
alter table profiles enable row level security;
alter table documents_rag enable row level security;
alter table flashcards enable row level security;
alter table study_logs enable row level security;
