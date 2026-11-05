from django.apps import AppConfig, apps
from django.db import connections
from django.db.models.signals import post_migrate


def protect_django_tables(sender, using, **kwargs):
    """Liga RLS nas tabelas do Django, inclusive sessões e usuários.

    Elas ficam no schema public, que o Supabase expõe pela API REST com a chave
    anon. Sem policies, a API não lê nada; o Django conecta como dono da tabela.
    """
    connection = connections[using]
    models = apps.get_models(include_auto_created=True)
    tables = {model._meta.db_table for model in models if model._meta.managed}
    tables.add("django_migrations")
    with connection.cursor() as cursor:
        for table in sorted(tables & set(connection.introspection.table_names(cursor))):
            cursor.execute(
                f"alter table {connection.ops.quote_name(table)} enable row level security"
            )


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        post_migrate.connect(protect_django_tables, sender=self)
