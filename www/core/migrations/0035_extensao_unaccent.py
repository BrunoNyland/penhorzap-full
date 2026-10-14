from django.db import migrations


def criar_unaccent(apps, schema_editor):
    # O backend penhorzap.postgresql_sem_acento usa UNACCENT nos lookups i*.
    # No SQLite (testes) não há o que criar. unaccent é extensão "trusted":
    # o dono do banco cria sem ser superusuário.
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_documento_recebido"),
    ]

    operations = [
        migrations.RunPython(criar_unaccent, migrations.RunPython.noop),
    ]
