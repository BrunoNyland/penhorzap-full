"""Corrige os Schedules do django-q2 criados nas migrations 0007 e 0029.

As duas usaram `repeats=0`, que para o django-q2 quer dizer "não repetir
mais": o agendador exclui esses registros (`exclude(repeats=0)`), então
nenhum dos dois rodou desde que foi criado. O valor de "para sempre" é -1.

- penhorzap_verificar_encerramento passa a repetir (repeats=-1).
- penhorzap_verificar_versao_evolution é apagado: comparava a Evolution com
  a imagem do Docker Hub e mandava atualizar o docker-compose, mas a Evolution
  roda de um fork próprio, sem Docker, à frente do upstream; quem acompanha
  versão nova agora é o vigia-whatsapp da VPS.
"""
from django.db import migrations


def corrigir(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    banco = schema_editor.connection.alias
    Schedule.objects.using(banco).update_or_create(
        name="penhorzap_verificar_encerramento",
        defaults=dict(
            func="whatsapp.tasks.verificar_encerramento",
            hook="",
            schedule_type="C",  # Cron
            cron="*/5 * * * *",
            repeats=-1,
        ),
    )
    Schedule.objects.using(banco).filter(name="penhorzap_verificar_versao_evolution").delete()


def desfazer(apps, schema_editor):
    """Volta ao estado das migrations 0007 e 0029 (os dois parados)."""
    Schedule = apps.get_model("django_q", "Schedule")
    banco = schema_editor.connection.alias
    Schedule.objects.using(banco).filter(name="penhorzap_verificar_encerramento").update(repeats=0)
    Schedule.objects.using(banco).update_or_create(
        name="penhorzap_verificar_versao_evolution",
        defaults=dict(
            func="whatsapp.tasks.verificar_versao_evolution",
            hook="",
            schedule_type="C",  # Cron
            cron="0 6 * * *",
            repeats=0,
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_mensagem_midia_indisponivel"),
    ]

    operations = [
        migrations.RunPython(corrigir, desfazer),
    ]
