from django.conf import settings
from django.db import connection
from django.test.runner import DiscoverRunner


class SupabaseSchemaTestRunner(DiscoverRunner):
    """Cria as tabelas de domínio a partir do schema.sql real.

    Essas tabelas são `managed = False`, então o migrate não as cria. O banco de
    teste é novo e não tem o schema `auth` do Supabase, por isso ele é simulado.
    """

    def setup_databases(self, **kwargs):
        config = super().setup_databases(**kwargs)
        schema = (settings.BASE_DIR / "supabase" / "schema.sql").read_text(encoding="utf-8")
        with connection.cursor() as cursor:
            cursor.execute("select to_regclass('public.profiles')")
            if cursor.fetchone()[0] is None:
                cursor.execute("create schema if not exists auth")
                cursor.execute("create table if not exists auth.users (id uuid primary key)")
                cursor.execute(schema)
        return config
