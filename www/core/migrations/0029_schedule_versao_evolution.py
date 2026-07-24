"""Cria o Schedule do django-q2 que roda verificar_versao_evolution 1x/dia
(6h da manhã) -- checa versão nova da Evolution API no Docker Hub."""
from django.db import migrations


def criar_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.using(schema_editor.connection.alias).update_or_create(
        name="penhorzap_verificar_versao_evolution",
        defaults=dict(
            func="whatsapp.tasks.verificar_versao_evolution",
            hook="",
            schedule_type="C",  # Cron
            cron="0 6 * * *",
            repeats=0,
        ),
    )


def remover_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.using(schema_editor.connection.alias).filter(
        name="penhorzap_verificar_versao_evolution"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_evolution_version_status"),
    ]

    operations = [
        migrations.RunPython(criar_schedule, remover_schedule),
    ]
