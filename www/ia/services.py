"""Gemini-backed message classification for the WhatsApp assistant.

GEMINI_API_KEY is empty until the user provisions it -- extrair_intencao()
must never raise: any failure (missing key, timeout, bad response) degrades
to a safe "precisa_humano=True" result, so the webhook/async task pipeline
keeps working end to end without the AI.

A partir do WS-A a Gemini é um CLASSIFICADOR PURO: ela nunca redige texto
que chega ao cliente (removido `resposta_sugerida`/`resposta_faq`). Todo
texto nasce de templates em `core.models.MensagensConfig`, renderizados em
Python (`whatsapp.respostas_contrato`). Isso também encolhe drasticamente o
prompt (sem persona/regras de redação) e o output (só rótulos JSON).
"""
import logging

from django.conf import settings

from core.mensagens_defaults import DEFAULT_SYSTEM_PROMPT

from .schemas import ClassificacaoLote

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-3.1-flash-lite"


def _config_textos() -> str:
    """Lê o prompt editável em MensagensConfig, com fallback para o
    DEFAULT_SYSTEM_PROMPT caso o banco esteja indisponível ou o campo esteja
    vazio. Import de core.models feito aqui dentro (não no topo do módulo)
    para preservar a garantia de que extrair_intencao() nunca levanta, mesmo
    que o app registry/DB não estejam prontos."""
    try:
        from core.models import MensagensConfig

        cfg = MensagensConfig.get_solo()
        return cfg.system_prompt or DEFAULT_SYSTEM_PROMPT
    except Exception:  # noqa: BLE001 - config lookup never breaks extrair_intencao
        logger.exception("_config_textos: falha ao ler MensagensConfig, usando default")
        return DEFAULT_SYSTEM_PROMPT


def _formatar_contratos(contratos_cliente):
    """Só o necessário para a IA desambiguar contratos -- SEM nenhum valor
    financeiro (isso fica inteiramente no Python/renderer, nunca no prompt)."""
    if not contratos_cliente:
        return "(cliente sem contratos ativos nos dados fornecidos)"
    linhas = []
    for c in contratos_cliente:
        parcelado = "sim" if c.get("parcelado") else "nao"
        linhas.append(
            f"contrato={c.get('contrato')} vencimento={c.get('data_vencimento')} parcelado={parcelado}"
        )
    return "\n".join(linhas)


def _formatar_historico(historico_mensagens):
    if not historico_mensagens:
        return "(sem histórico)"
    return "\n".join(
        f"- [{m.get('direcao', '?')}] {m.get('texto', '')}" for m in historico_mensagens
    ) or "(sem histórico)"


def _formatar_faqs(faqs):
    if not faqs:
        return "(sem FAQ cadastrado)"
    return "\n".join(f"- ID: {f.get('id')}\n  P: {f.get('pergunta')}" for f in faqs) or "(sem FAQ cadastrado)"


def _formatar_mensagens_lote(mensagens_lote) -> str:
    """Formata o lote de mensagens não respondidas do cliente numa lista
    numerada -- nesta fase (WS-A v3/Fase 2) o processamento ainda é
    imediato (1 mensagem por task, o debounce é a Fase 3), então o lote
    normalmente tem 1 item; o formato já suporta N para quando o debounce
    passar a acumular várias mensagens antes de chamar a IA."""
    if not mensagens_lote:
        return "(nenhuma mensagem)"
    return "\n".join(f"{i}. {texto}" for i, texto in enumerate(mensagens_lote, start=1))


def _montar_prompt(mensagens_lote, historico_mensagens, contratos_cliente, faqs,
                    identificado, db_atualizada, contato_tipo):
    if isinstance(mensagens_lote, str):
        mensagens_lote = [mensagens_lote]

    estado = (
        f"identificado={'sim' if identificado else 'nao'}\n"
        f"database_atualizada={'sim' if db_atualizada else 'nao'}\n"
        f"contato_tipo={contato_tipo}"
    )

    return f"""\
HISTÓRICO RECENTE DA CONVERSA:
{_formatar_historico(historico_mensagens)}

MENSAGENS DO CLIENTE (não respondidas, em ordem):
{_formatar_mensagens_lote(mensagens_lote)}

ESTADO:
{estado}

CONTRATOS ATIVOS DO CLIENTE (contrato, vencimento, parcelado -- só para desambiguar; NUNCA contêm valores):
{_formatar_contratos(contratos_cliente)}

FAQ DISPONÍVEL (id + pergunta):
{_formatar_faqs(faqs)}
"""


def _resultado_fallback(motivo: str) -> ClassificacaoLote:
    logger.warning("extrair_intencao: usando fallback neutro (%s)", motivo)
    return ClassificacaoLote(precisa_humano=True)


def extrair_intencao(
    mensagens_lote,
    historico_mensagens,
    contratos_cliente,
    faqs,
    *,
    identificado=False,
    db_atualizada=True,
    contato_tipo="desconhecido",
) -> ClassificacaoLote:
    """Classifica o LOTE de mensagens não respondidas do cliente via Gemini
    (saída estruturada Pydantic, schema `ClassificacaoLote` -- multi-ação:
    a IA identifica TODAS as solicitações do lote, não só uma). Nunca
    levanta. `mensagens_lote` aceita tanto `str` (mensagem única, forma
    usada nesta fase e pelo simulador) quanto `list[str]` (lote de N
    mensagens não respondidas, em ordem -- forma que a Fase 3/debounce vai
    passar a usar); `str` é envelopado em `[str]` internamente.

    Os parâmetros keyword-only descrevem o estado da conversa que a IA
    precisa saber (contato já identificado -- por telefone cadastrado ou CPF
    digitado --, database fresca, tipo de contato). As garantias duras
    (validar CPF, filtrar contratos, checar freshness, negar dados a
    desconhecidos) são aplicadas pelo chamador (whatsapp.tasks), NÃO pela
    IA -- e o texto de resposta nunca vem daqui: nasce de templates
    renderizados em Python a partir dos campos classificados."""
    if isinstance(mensagens_lote, str):
        mensagens_lote = [mensagens_lote]

    system_prompt = _config_textos()

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return _resultado_fallback("GEMINI_API_KEY não configurada")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return _resultado_fallback("SDK google-genai não disponível")

    prompt = _montar_prompt(
        mensagens_lote, historico_mensagens, contratos_cliente, faqs,
        identificado, db_atualizada, contato_tipo,
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=ClassificacaoLote,
                temperature=0.2,
            ),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, ClassificacaoLote):
            return parsed
        if parsed is not None:
            return ClassificacaoLote.model_validate(parsed)
        return ClassificacaoLote.model_validate_json(response.text)
    except Exception as exc:  # noqa: BLE001 - never let Gemini errors break the webhook
        return _resultado_fallback(f"erro ao chamar Gemini: {exc}")
