"""O verificar_encerramento passa de cron para "a cada 5 minutos".

Expressão cron no django-q2 exige o pacote croniter, que o projeto não
instala: depois da 0037 o agendador passou a registrar "Please install
croniter to enable cron expressions" a cada 30 s, sem rodar a tarefa. O
tipo MINUTES é nativo e faz o mesmo.
"""
from django.db import migrations
from django.utils import timezone


def para_minutos(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.using(schema_editor.connection.alias).filter(
        name="penhorzap_verificar_encerramento"
    ).update(schedule_type="I", minutes=5, cron=None, next_run=timezone.now())


def para_cron(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.using(schema_editor.connection.alias).filter(
        name="penhorzap_verificar_encerramento"
    ).update(schedule_type="C", minutes=None, cron="*/5 * * * *")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0037_corrige_schedules"),
    ]

    operations = [
        migrations.RunPython(para_minutos, para_cron),
    ]
