"""Thin wrapper around the Evolution API (WhatsApp gateway).

The Evolution API instance is provisioned separately (Docker, listening on
EVOLUTION_API_URL). This client never raises on network/HTTP errors -- it
logs and returns False/[], so a flaky WhatsApp gateway never takes down the
Django webhook or the async task worker.

NOTE: os endpoints de agenda (`fetch_contacts`) e `mark_as_read` são baseados
na Evolution API v2 e podem precisar de ajuste conforme a versão real em uso
(v2.3.7 no docker-compose deste projeto). Em caso de 404/erro eles fall-safe
para []/False — o fluxo do bot continua funcionando, só sem a classificação
automática de contatos salvos.
"""
import base64
import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


class EvolutionClient:
    def __init__(self, base_url=None, api_key=None, instance=None):
        self.base_url = (base_url or settings.EVOLUTION_API_URL).rstrip("/")
        self.api_key = api_key or settings.EVOLUTION_API_KEY
        self.instance = instance or settings.EVOLUTION_INSTANCE

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "apikey": self.api_key,
        }

    def send_text(self, numero: str, texto: str) -> bool:
        """Send a plain text message to `numero` (E.164, e.g. +5567999755980)."""
        url = f"{self.base_url}/message/sendText/{self.instance}"
        payload = {"number": numero, "text": texto}
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            logger.exception("Falha ao enviar texto via Evolution API para %s", numero)
            return False

    def get_connection_state(self) -> str:
        """Return the instance connection state: 'open', 'connecting', 'close', or 'unknown'."""
        url = f"{self.base_url}/instance/connectionState/{self.instance}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return (resp.json().get("instance") or {}).get("state", "unknown")
        except requests.RequestException:
            logger.exception("Falha ao consultar estado da conexão Evolution API")
            return "unknown"

    def get_qrcode_base64(self):
        """Return the current pairing QR code as base64 (no data: prefix), or None."""
        url = f"{self.base_url}/instance/connect/{self.instance}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            b64 = data.get("base64") or (data.get("qrcode") or {}).get("base64")
            if b64 and "," in b64:
                b64 = b64.split(",", 1)[1]
            return b64
        except requests.RequestException:
            logger.exception("Falha ao obter QR code da Evolution API")
            return None

    def send_media_pdf(self, numero: str, caminho_ou_base64: str, filename: str) -> bool:
        """Send a PDF document to `numero`.

        `caminho_ou_base64` may be a filesystem path to a PDF or an already
        base64-encoded string -- either way we end up sending base64 media,
        which is what the Evolution API `sendMedia` endpoint expects.
        """
        media_b64 = caminho_ou_base64
        if os.path.isfile(caminho_ou_base64):
            with open(caminho_ou_base64, "rb") as fh:
                media_b64 = base64.b64encode(fh.read()).decode("ascii")

        url = f"{self.base_url}/message/sendMedia/{self.instance}"
        payload = {
            "number": numero,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "fileName": filename,
            "media": media_b64,
        }
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            logger.exception("Falha ao enviar PDF via Evolution API para %s", numero)
            return False

    def send_file(self, numero: str, file_path: str, filename: str, caption: str = "") -> bool:
        """Send any file (image, video, audio, document) to `numero` using Evolution API."""
        if not os.path.isfile(file_path):
            logger.error("Arquivo não encontrado no caminho: %s", file_path)
            return False

        import mimetypes
        mimetype, _ = mimetypes.guess_type(file_path)
        if not mimetype:
            mimetype = "application/octet-stream"

        # Map mimetype to Evolution's mediatype
        if mimetype.startswith("image/"):
            mediatype = "image"
        elif mimetype.startswith("video/"):
            mediatype = "video"
        elif mimetype.startswith("audio/"):
            mediatype = "audio"
        else:
            mediatype = "document"

        with open(file_path, "rb") as fh:
            media_b64 = base64.b64encode(fh.read()).decode("ascii")

        url = f"{self.base_url}/message/sendMedia/{self.instance}"
        payload = {
            "number": numero,
            "mediatype": mediatype,
            "mimetype": mimetype,
            "fileName": filename,
            "media": media_b64,
        }
        if caption:
            payload["caption"] = caption

        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            logger.exception("Falha ao enviar arquivo (%s) via Evolution API para %s", filename, numero)
            return False

    # --- Contatos / leitura (provisional, v2) --------------------------------

    def fetch_contacts(self):
        """Baixa a agenda de contatos salva no aparelho conectado.

        Retorna uma lista de dicts {remote_jid, nome} (nome = nome salvo na
        agenda do dono, ex.: "PHN_12345678901_Jose"). Endpoint provisional
        (Evolution v2); em qualquer erro retorna [] — o fluxo do bot cai no
        fallback de classificação por Telefone/ContatoSalvo manual.
        """
        # Endpoint variou entre versões v2; permite override via env.
        path = os.environ.get("EVOLUTION_CONTACTS_PATH", f"/chat/findContacts/{self.instance}")
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            logger.warning("fetch_contacts: endpoint %s indisponível (sync de contatos pulado)", url)
            return []
        except ValueError:
            logger.warning("fetch_contacts: resposta não-JSON de %s", url)
            return []

        items = data if isinstance(data, list) else (data.get("contacts") or data.get("data") or [])
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            jid = item.get("id") or item.get("jid") or item.get("remoteJid") or ""
            nome = item.get("name") or item.get("notifyName") or item.get("pushName") or ""
            if jid:
                out.append({"remote_jid": str(jid), "nome": str(nome or "")})
        return out

    def mark_as_read(self, remote_jid: str, message_id: str | None = None) -> bool:
        """Marca mensagens como lidas (best-effort, só cosmético)."""
        if not remote_jid:
            return False
        path = os.environ.get("EVOLUTION_READ_PATH", f"/chat/markMessageAsRead/{self.instance}")
        url = f"{self.base_url}{path}"
        payload = {"readMessages": [{"id": message_id or "", "remoteJid": remote_jid}]}
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            logger.debug("mark_as_read: falha (não-crítico) para %s", remote_jid)
            return False

    def logout(self) -> bool:
        """Disconnect/logout the instance session."""
        url = f"{self.base_url}/instance/logout/{self.instance}"
        try:
            resp = requests.delete(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            logger.exception("Falha ao efetuar logout na Evolution API")
            return False


def get_client() -> EvolutionClient:
    return EvolutionClient()
