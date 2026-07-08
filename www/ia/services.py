"""Gemini-backed intent extraction for the WhatsApp assistant.

GEMINI_API_KEY is empty until the user provisions it -- extrair_intencao()
must never raise: any failure (missing key, timeout, bad response) degrades
to a safe "precisa_humano=True" result with a neutral message, so the
webhook/async task pipeline keeps working end to end without the AI.
"""
import logging

from django.conf import settings

from core.mensagens_defaults import DEFAULT_MSG_NEUTRA_PADRAO, DEFAULT_SYSTEM_PROMPT

from .schemas import IntencaoCliente, TipoIntencao

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"


def _config_textos():
    """Lê o prompt/mensagem neutra editáveis em MensagensConfig, com fallback
    para os DEFAULT_* caso o banco esteja indisponível ou os campos estejam
    vazios. Import de core.models feito aqui dentro (não no topo do módulo)
    para preservar a garantia de que extrair_intencao() nunca levanta,
    mesmo que o app registry/DB não estejam prontos."""
    try:
        from core.models import MensagensConfig

        cfg = MensagensConfig.get_solo()
        system_prompt = cfg.system_prompt or DEFAULT_SYSTEM_PROMPT
        msg_neutra = cfg.msg_neutra_padrao or DEFAULT_MSG_NEUTRA_PADRAO
        return system_prompt, msg_neutra
    except Exception:  # noqa: BLE001 - config lookup never breaks extrair_intencao
        logger.exception("_config_textos: falha ao ler MensagensConfig, usando defaults")
        return DEFAULT_SYSTEM_PROMPT, DEFAULT_MSG_NEUTRA_PADRAO


def _formatar_contratos(contratos_cliente):
    if not contratos_cliente:
        return "(cliente sem contratos ativos nos dados fornecidos)"
    linhas = []
    for c in contratos_cliente:
        partes = [f"contrato={c.get('contrato')}"]
        if c.get("data_vencimento") is not None:
            partes.append(f"vencimento={c.get('data_vencimento')}")
        if c.get("vlr_emprestimo") is not None:
            partes.append(f"valor_contrato={c.get('vlr_emprestimo')}")
        if c.get("vlr_liquido") is not None:
            partes.append(f"valor_quitacao={c.get('vlr_liquido')}")
        for prazo in (30, 60, 90, 120, 150, 180):
            val = c.get(f"vlr_renovacao_{prazo}")
            if val is not None:
                partes.append(f"valor_renovacao_{prazo}={val}")
        if c.get("parcelado"):
            partes.append("parcelado=sim")
            if c.get("vlr_parcela") is not None:
                partes.append(f"valor_parcela={c.get('vlr_parcela')}")
        linhas.append(" - ".join(partes))
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


def _montar_prompt(mensagem_atual, historico_mensagens, contratos_cliente, faqs,
                   cpf_verificado, db_atualizada, contato_tipo, cliente_cpf, cliente_nome,
                   ultima_solicitacao):
    estado = (
        f"cpf_verificado={'sim' if cpf_verificado else 'nao'}\n"
        f"database_atualizada={'sim' if db_atualizada else 'nao'}\n"
        f"contato_tipo={contato_tipo}\n"
        f"cliente_cpf={cliente_cpf or '(desconhecido)'}\n"
        f"cliente_nome={cliente_nome or '(desconhecido)'}"
    )
    if ultima_solicitacao:
        estado += (
            f"\nultima_solicitacao=tipo={ultima_solicitacao.get('tipo')} "
            f"prazo_dias={ultima_solicitacao.get('prazo_dias')} "
            f"contratos={ultima_solicitacao.get('contratos')} "
            f"status={ultima_solicitacao.get('status')}"
        )

    return f"""\
HISTÓRICO RECENTE DA CONVERSA:
{_formatar_historico(historico_mensagens)}

MENSAGEM ATUAL DO CLIENTE:
{mensagem_atual}

ESTADO:
{estado}

CONTRATOS ATIVOS DO CLIENTE (única fonte permitida para valores/datas; já filtrados para o CPF verificado):
{_formatar_contratos(contratos_cliente)}

FAQ DISPONÍVEL:
{_formatar_faqs(faqs)}
"""


def _resultado_fallback(motivo: str, mensagem_neutra: str) -> IntencaoCliente:
    logger.warning("extrair_intencao: usando fallback neutro (%s)", motivo)
    return IntencaoCliente(
        tipo_intencao=TipoIntencao.OUTRO,
        cpf_extraido=None,
        duvida_cliente=None,
        resposta_faq=None,
        faq_id=None,
        solicitacoes=[],
        pronto_para_criar_solicitacao=False,
        resposta_sugerida=mensagem_neutra,
        precisa_humano=True,
    )


def extrair_intencao(
    mensagem_atual,
    historico_mensagens,
    contratos_cliente,
    faqs,
    *,
    cpf_verificado=False,
    db_atualizada=True,
    contato_tipo="desconhecido",
    cliente_cpf="",
    cliente_nome="",
    ultima_solicitacao=None,
) -> IntencaoCliente:
    """Extrai a intenção do cliente via Gemini (saída estruturada Pydantic).

    Nunca levanta. Os parâmetros keyword-only descrevem o estado da conversa
    que a IA precisa saber (CPF já verificado? database fresca? quem é o
    cliente?). As garantias duras (validar CPF, filtrar contratos, checar
    freshness) são aplicadas pelo chamador (whatsapp.tasks), NÃO pela IA.
    """
    system_prompt, msg_neutra = _config_textos()

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        return _resultado_fallback("GEMINI_API_KEY não configurada", msg_neutra)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return _resultado_fallback("SDK google-genai não disponível", msg_neutra)

    prompt = _montar_prompt(
        mensagem_atual, historico_mensagens, contratos_cliente, faqs,
        cpf_verificado, db_atualizada, contato_tipo, cliente_cpf, cliente_nome,
        ultima_solicitacao,
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=IntencaoCliente,
                temperature=0.2,
            ),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, IntencaoCliente):
            return parsed
        if parsed is not None:
            return IntencaoCliente.model_validate(parsed)
        return IntencaoCliente.model_validate_json(response.text)
    except Exception as exc:  # noqa: BLE001 - never let Gemini errors break the webhook
        return _resultado_fallback(f"erro ao chamar Gemini: {exc}", msg_neutra)
