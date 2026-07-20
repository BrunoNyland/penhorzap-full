import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from core.models import Conversa, Mensagem

logger = logging.getLogger(__name__)


# Nós que o WhatsApp usa para embrulhar o conteúdo real (mensagem efêmera/
# "apagar após visualizar" e mídia de "visualização única") -- sem
# desembrulhar, nenhum parser encontra imageMessage/audioMessage/... direto
# e a mensagem vira "vazia" (sem texto, sem mídia) tanto no webhook quanto
# no download de mídia do painel.
_NOS_EMBRULHO_MENSAGEM = (
    "ephemeralMessage",
    "viewOnceMessage",
    "viewOnceMessageV2",
    "viewOnceMessageV2Extension",
)


def desembrulhar_no_mensagem(message: dict) -> dict:
    """Desembrulha recursivamente (até 5 níveis, contra payload malformado
    ou recursivo) os nós de mensagem efêmera/visualização única do WhatsApp
    até achar o nó de conteúdo real (texto ou mídia). Devolve `message`
    inalterado se não houver embrulho conhecido."""
    if not message:
        return message or {}
    for _ in range(5):
        proximo = None
        for chave in _NOS_EMBRULHO_MENSAGEM:
            if chave in message:
                proximo = (message.get(chave) or {}).get("message") or {}
                break
        if proximo is None:
            break
        message = proximo
    return message


def _extrair_conteudo(message: dict) -> tuple[str, str]:
    """Extrai (texto, tipo_midia) do nó `message` do payload da Evolution.
    texto = corpo/legenda a persistir em `Mensagem.texto`; tipo_midia = um
    dos valores de `Mensagem.TipoMidia` ou "" quando é mensagem de texto puro."""
    message = desembrulhar_no_mensagem(message)
    if not message:
        return "", ""
    if "conversation" in message:
        return message.get("conversation") or "", ""
    if "extendedTextMessage" in message:
        return (message.get("extendedTextMessage") or {}).get("text") or "", ""
    if "imageMessage" in message:
        return (message.get("imageMessage") or {}).get("caption") or "", "image"
    if "videoMessage" in message:
        return (message.get("videoMessage") or {}).get("caption") or "", "video"
    if "documentMessage" in message:
        doc = message.get("documentMessage") or {}
        return doc.get("caption") or doc.get("fileName") or "", "document"
    if "audioMessage" in message:
        return "", "audio"
    return "", ""


@csrf_exempt
@require_POST
def whatsapp_webhook(request):
    token = request.headers.get("X-Webhook-Token", "")
    if not settings.WEBHOOK_TOKEN or token != settings.WEBHOOK_TOKEN:
        return JsonResponse({"detail": "forbidden"}, status=403)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid json"}, status=400)

    # Filter out non-message events from the Evolution API
    event = str(body.get("event") or "").strip().lower()
    if event and event not in ("messages.upsert", "send.message"):
        return JsonResponse(
            {"status": "ignored", "reason": f"unhandled event: {event}"}, status=200
        )

    try:
        data = body.get("data") or {}
        key = data.get("key") or {}
        remote_jid = key.get("remoteJid", "")

        if remote_jid.endswith("@g.us"):
            return JsonResponse({"status": "ignored", "reason": "group"}, status=200)

        push_name = str(data.get("pushName") or body.get("pushName") or "")

        # Mensagens enviadas por nós (fromMe=true): persistir como OUT para manter
        # o histórico visível no painel, mas NÃO disparar o bot (evitar loop).
        if key.get("fromMe"):
            wa_message_id = key.get("id") or None
            if wa_message_id and Mensagem.objects.filter(wa_message_id=wa_message_id).exists():
                return JsonResponse({"status": "ignored", "reason": "duplicate"}, status=200)
            texto, tipo_midia = _extrair_conteudo(data.get("message") or {})
            conversa, _ = Conversa.objects.get_or_create(remote_jid=remote_jid or "desconhecido")
            Mensagem.objects.create(
                conversa=conversa,
                direcao=Mensagem.Direcao.OUT,
                texto=texto,
                tipo_midia=tipo_midia,
                wa_message_id=wa_message_id,
                payload_bruto=body,
            )
            # Classifica a conversa (ContatoSalvo > Telefone > sem push_name)
            try:
                from whatsapp.tasks import classificar_e_atualizar_conversa

                classificar_e_atualizar_conversa(conversa, push_name)
            except Exception:
                logger.debug("Classificação no webhook (OUT) falhou (não-crítico)", exc_info=True)
            return JsonResponse({"status": "ok", "direction": "out"}, status=200)

        wa_message_id = key.get("id") or None

        if wa_message_id and Mensagem.objects.filter(wa_message_id=wa_message_id).exists():
            return JsonResponse({"status": "ignored", "reason": "duplicate"}, status=200)

        texto, tipo_midia = _extrair_conteudo(data.get("message") or {})

        conversa, _ = Conversa.objects.get_or_create(remote_jid=remote_jid or "desconhecido")

        mensagem = Mensagem.objects.create(
            conversa=conversa,
            direcao=Mensagem.Direcao.IN,
            texto=texto,
            tipo_midia=tipo_midia,
            wa_message_id=wa_message_id,
            push_name=push_name,
            payload_bruto=body,
        )

        # Classifica a conversa (ContatoSalvo > Telefone > pushName) mesmo
        # com o bot desligado, para que o painel mostre nome/tipo/CPF.
        try:
            from whatsapp.tasks import classificar_e_atualizar_conversa

            classificar_e_atualizar_conversa(conversa, push_name)
        except Exception:
            logger.debug("Classificação no webhook (IN) falhou (não-crítico)", exc_info=True)
    except Exception:
        logger.exception("Falha ao processar payload do webhook whatsapp")
        # Ack anyway: we don't want Evolution API retrying a payload we can't parse.
        return JsonResponse({"status": "error_logged"}, status=200)

    try:
        async_task("whatsapp.tasks.process_mensagem", mensagem.id)
    except Exception:
        logger.exception("Falha ao enfileirar processamento assíncrono da mensagem %s", mensagem.id)

    return JsonResponse({"status": "ok"}, status=200)
