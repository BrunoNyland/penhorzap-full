from django.db import migrations

# Chave do payload da Evolution (data.message.<chave>) -> Mensagem.TipoMidia
_MIDIA_KEYS = {
    "imageMessage": "image",
    "audioMessage": "audio",
    "videoMessage": "video",
    "documentMessage": "document",
}


def backfill_tipo_midia_e_identificacao(apps, schema_editor):
    Mensagem = apps.get_model("core", "Mensagem")
    Conversa = apps.get_model("core", "Conversa")

    mensagens_sem_tipo = Mensagem.objects.filter(tipo_midia="").exclude(payload_bruto={})
    for mensagem in mensagens_sem_tipo.iterator():
        message = ((mensagem.payload_bruto or {}).get("data") or {}).get("message") or {}
        if not isinstance(message, dict):
            continue
        tipo_midia = ""
        for chave, tipo in _MIDIA_KEYS.items():
            if message.get(chave):
                tipo_midia = tipo
                break
        if tipo_midia:
            mensagem.tipo_midia = tipo_midia
            mensagem.save(update_fields=["tipo_midia"])

    Conversa.objects.exclude(cpf_verificado="").filter(identificacao="nenhum").update(identificacao="cpf")


def noop(apps, schema_editor):
    """Backfill não é reversível de forma exata (não distinguimos 'nenhum'
    original de 'cpf' setado por esta migração); reverse é intencionalmente
    um no-op."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_conversa_identificacao_conversa_processando_desde_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_tipo_midia_e_identificacao, noop),
    ]
