"""
Recupera mensagens que chegaram na Evolution API mas cujo webhook falhou (ex.:
reconexão/resync da sessão WhatsApp, que faz a Evolution reenviar um backlog
de retries -- alguns com token stale, rejeitados com 403 e descartados pra
sempre pela própria Evolution).

Lê direto do Postgres da Evolution (mesma fonte que alimenta o webhook) e
insere só o que estiver faltando no nosso banco, comparando por
wa_message_id (não duplica o que já chegou certo pelo webhook). Não dispara
o bot para essas mensagens -- é só preenchimento de histórico.

Uso:
    python manage.py backfill_evolution_messages [--since-hours 48]
"""

import json
import logging
import subprocess
from datetime import datetime
from datetime import timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.utils import timezone as dj_timezone

from core.models import Conversa, Mensagem
from whatsapp.tasks import classificar_e_atualizar_conversa
from whatsapp.views import _extrair_conteudo

logger = logging.getLogger("core.backfill_evolution_messages")

POSTGRES_CONTAINER = "penhorzap_postgres"
POSTGRES_USER = "evolution"
POSTGRES_DB = "evolution"


class Command(BaseCommand):
    help = (
        "Recupera mensagens do WhatsApp presentes na Evolution API mas ausentes no "
        "nosso banco (webhook falhou). Dedupe por wa_message_id."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--since-hours",
            type=int,
            default=48,
            help="Janela de horas pra trás a considerar (default: 48).",
        )

    def handle(self, *args, **options):
        since_hours = options["since_hours"]
        cutoff_ts = int(dj_timezone.now().timestamp()) - since_hours * 3600

        sql = (
            "SELECT row_to_json(t) FROM ("
            'SELECT id, key, "pushName", "messageTimestamp", message '
            'FROM evolution_api."Message" '
            f'WHERE "messageTimestamp" >= {cutoff_ts} '
            "AND (key->>'remoteJid') NOT LIKE '%@g.us' "
            'ORDER BY "messageTimestamp" ASC'
            ") t;"
        )

        resultado = subprocess.run(
            [
                "docker",
                "exec",
                POSTGRES_CONTAINER,
                "psql",
                "-U",
                POSTGRES_USER,
                "-d",
                POSTGRES_DB,
                "-t",
                "-A",
                "-c",
                sql,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if resultado.returncode != 0:
            self.stderr.write(
                self.style.ERROR(f"Falha ao consultar Postgres da Evolution: {resultado.stderr}")
            )
            return

        linhas = [linha for linha in resultado.stdout.splitlines() if linha.strip()]
        self.stdout.write(
            f"{len(linhas)} mensagens encontradas na Evolution (janela de {since_hours}h)."
        )

        criadas = 0
        ja_existiam = 0
        ignoradas = 0

        for linha in linhas:
            try:
                row = json.loads(linha)
            except json.JSONDecodeError:
                ignoradas += 1
                continue

            key = row.get("key") or {}
            remote_jid = key.get("remoteJid") or ""
            wa_message_id = key.get("id") or None
            if not remote_jid or not wa_message_id:
                ignoradas += 1
                continue

            if Mensagem.objects.filter(wa_message_id=wa_message_id).exists():
                ja_existiam += 1
                continue

            message = row.get("message") or {}
            push_name = row.get("pushName") or ""
            ts = row.get("messageTimestamp")

            texto, tipo_midia = _extrair_conteudo(message)
            direcao = Mensagem.Direcao.OUT if key.get("fromMe") else Mensagem.Direcao.IN

            mensagem_em = None
            if ts:
                try:
                    mensagem_em = datetime.fromtimestamp(int(ts), tz=dt_timezone.utc)
                except (TypeError, ValueError, OSError):
                    mensagem_em = None

            conversa, _ = Conversa.objects.get_or_create(remote_jid=remote_jid)

            Mensagem.objects.create(
                conversa=conversa,
                direcao=direcao,
                texto=texto,
                tipo_midia=tipo_midia,
                wa_message_id=wa_message_id,
                push_name=push_name if direcao == Mensagem.Direcao.IN else "",
                payload_bruto={
                    "event": "messages.upsert",
                    "data": {
                        "key": key,
                        "pushName": push_name,
                        "message": message,
                        "messageTimestamp": ts,
                    },
                },
                mensagem_em=mensagem_em,
            )
            try:
                classificar_e_atualizar_conversa(conversa, push_name)
            except Exception:
                logger.debug("Classificação no backfill falhou (não-crítico)", exc_info=True)

            criadas += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Backfill concluído: {criadas} mensagens novas, "
                f"{ja_existiam} já existiam, {ignoradas} ignoradas."
            )
        )
