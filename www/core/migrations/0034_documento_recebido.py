import logging

from django.db import migrations, models

logger = logging.getLogger("core.migrations.0034_documento_recebido")

MIDIA_ANTIGO = (
    "Recebi seu áudio/vídeo, mas por aqui eu só consigo ler mensagens de "
    "texto 🙏 Pode escrever sua dúvida que já te respondo."
)
MIDIA_NOVO = (
    "Recebi sua mídia, mas por aqui eu só consigo ler mensagens de "
    "texto 🙏 Pode escrever sua dúvida que já te respondo."
)


def substituir_defaults_customizaveis(apps, schema_editor):
    MensagensConfig = apps.get_model("core", "MensagensConfig")
    config = MensagensConfig.objects.filter(pk=1).first()
    if config is None:
        return

    if (config.msg_midia_nao_suportada or "").strip() == MIDIA_ANTIGO:
        config.msg_midia_nao_suportada = MIDIA_NOVO
        config.save(update_fields=["msg_midia_nao_suportada"])
        logger.info(
            "0034: msg_midia_nao_suportada padrão substituído (não falava mais "
            "só 'áudio/vídeo' -- também usada por imagem)."
        )
    else:
        logger.warning(
            "0034: msg_midia_nao_suportada salvo no banco é customizado -- NÃO foi substituído automaticamente."
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_cortesia_sem_pedido'),
    ]

    operations = [
        migrations.AddField(
            model_name='mensagensconfig',
            name='msg_documento_recebido',
            field=models.TextField(
                default='Recebi seu documento! 📎 Vou verificar por aqui com calma e te confirmo, combinado? 🙏',
                help_text='Documento (PDF etc., ex.: comprovante de pagamento) sem legenda e sem outra mensagem com texto pendente no mesmo lote.',
            ),
        ),
        migrations.AlterField(
            model_name='mensagensconfig',
            name='msg_midia_nao_suportada',
            field=models.TextField(
                default=MIDIA_NOVO,
                help_text='Áudio/vídeo/imagem sem legenda e sem outra mensagem com texto pendente no mesmo lote.',
            ),
        ),
        migrations.RunPython(substituir_defaults_customizaveis, noop_reverse),
    ]
