"""Fase 3 (debounce): `BotConfig.debounce_segundos` (segundos de silêncio do
cliente antes de a IA responder ao LOTE de mensagens não respondidas; 0 =
imediato/kill-switch) e `Mensagem.respondida_em` (controle de quais
mensagens IN já foram cobertas por uma resposta do bot -- determinística ou
via IA -- e portanto saem do lote do debounce).

Data migration: backfill `respondida_em=criado_em` para as IN existentes
(histórico já respondido antes desta fase não deve entrar em lotes novos).
"""
from django.db import migrations, models


def backfill_respondida_em(apps, schema_editor):
    Mensagem = apps.get_model("core", "Mensagem")
    Mensagem.objects.filter(direcao="in", respondida_em__isnull=True).update(
        respondida_em=models.F("criado_em")
    )


def noop_reverse(apps, schema_editor):
    """Backfill não é reversível de forma exata (não distinguimos o que foi
    carimbado por esta migração do que seria marcado organicamente depois);
    reverse é intencionalmente um no-op."""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_mensagensconfig_msg_duvida_anotada_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="botconfig",
            name="debounce_segundos",
            field=models.PositiveIntegerField(
                default=120,
                help_text="Segundos de silêncio do cliente antes de a IA responder. 0 = responder imediatamente. Respostas sem IA (CPF, saudação, mídia) continuam imediatas.",
            ),
        ),
        migrations.AddField(
            model_name="mensagem",
            name="respondida_em",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Quando o bot considerou esta mensagem IN respondida (controle do lote do debounce).",
            ),
        ),
        migrations.RunPython(backfill_respondida_em, noop_reverse),
    ]
