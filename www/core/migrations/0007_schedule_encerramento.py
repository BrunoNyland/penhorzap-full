"""Cria o Schedule do django-q2 que roda verificar_encerramento a cada
5 minutos (desliga o bot no horário de encerramento configurado)."""
from django.db import migrations


def criar_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.using(schema_editor.connection.alias).update_or_create(
        name="penhorzap_verificar_encerramento",
        defaults=dict(
            func="whatsapp.tasks.verificar_encerramento",
            hook="",
            schedule_type="C",  # Cron
            cron="*/5 * * * *",
            repeats=0,
        ),
    )


def remover_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.using(schema_editor.connection.alias).filter(
        name="penhorzap_verificar_encerramento"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_botconfig_ultimo_encerramento_auto"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(criar_schedule, remover_schedule),
    ]
