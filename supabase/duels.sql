-- Duelos entre dois usuários. Execute no SQL Editor do Supabase (uma vez, em bancos
-- que já têm o schema.sql aplicado). Bancos novos já recebem isto pelo schema.sql.
create table if not exists duels (
    id serial primary key,
    challenger_id uuid not null references profiles(id) on delete cascade,
    opponent_id uuid not null references profiles(id) on delete cascade,
    duration_days int not null check (duration_days between 1 and 30),
    status text not null default 'pending'
        check (status in ('pending', 'active', 'declined', 'cancelled')),
    starts_at timestamp with time zone,
    ends_at timestamp with time zone,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    check (challenger_id <> opponent_id)
);
create index if not exists duels_challenger_idx on duels (challenger_id, status);
create index if not exists duels_opponent_idx on duels (opponent_id, status);
alter table duels enable row level security;
