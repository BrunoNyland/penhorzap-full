import json
import logging

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from core.models import BotConfig, Conversa, Mensagem
from .evolution_client import get_client

logger = logging.getLogger(__name__)


@staff_member_required
def qrcode_view(request):
    client = get_client()
    state = client.get_connection_state()
    context = {"state": state, "bot_config": BotConfig.get_solo(), "active_nav": "conexao"}
    if state != "open":
        context["qrcode_base64"] = client.get_qrcode_base64()
    return render(request, "whatsapp/qrcode.html", context)


@staff_member_required
@require_POST
def toggle_bot(request):
    bot_config = BotConfig.get_solo()
    bot_config.ativo = not bot_config.ativo
    bot_config.save(update_fields=["ativo", "atualizado_em"])
    logger.info("Bot %s por %s", "ativado" if bot_config.ativo else "desativado", request.user)
    if bot_config.ativo:
        # Ao ativar: sincroniza a agenda (classifica PHN_ vs. pessoal) e
        # reprocessa mensagens não atendidas que chegaram enquanto desligado.
        async_task("whatsapp.tasks.sincronizar_contatos")
        async_task("whatsapp.tasks.processar_nao_lidas")
    return redirect(reverse("whatsapp:qrcode"))


def _extrair_texto(message: dict) -> str:
    if not message:
        return ""
    return (
        message.get("conversation")
        or (message.get("extendedTextMessage") or {}).get("text")
        or (message.get("imageMessage") or {}).get("caption")
        or (message.get("documentMessage") or {}).get("caption")
        or ""
    )


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
            texto = _extrair_texto(data.get("message") or {})
            conversa, _ = Conversa.objects.get_or_create(remote_jid=remote_jid or "desconhecido")
            Mensagem.objects.create(
                conversa=conversa,
                direcao=Mensagem.Direcao.OUT,
                texto=texto,
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

        texto = _extrair_texto(data.get("message") or {})

        conversa, _ = Conversa.objects.get_or_create(remote_jid=remote_jid or "desconhecido")

        mensagem = Mensagem.objects.create(
            conversa=conversa,
            direcao=Mensagem.Direcao.IN,
            texto=texto,
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
