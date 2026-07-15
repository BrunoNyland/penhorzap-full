"""Renderização determinística de respostas de contrato (WS-A).

A partir daqui a IA (Gemini) é só classificadora: nenhum texto que chega ao
cliente é gerado por ela. Este módulo pega os pedidos já classificados
(`InfoContratoPedido`) e os templates editáveis em `MensagensConfig` e
produz texto pronto para enviar via WhatsApp — os valores usados SEMPRE vêm
do banco (via `whatsapp.tasks._contratos_ativos_values`), nunca da IA.
"""
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from core.utils import parse_br_decimal
from ia.schemas import InfoContrato

logger = logging.getLogger(__name__)

PRAZOS_RENOVACAO = (30, 60, 90, 120, 150, 180)


def formatar_moeda(valor) -> str:
    """Formata um valor numérico como 'R$ 1.234,56', sem depender do locale
    do SO (o servidor pode não ter pt_BR instalado)."""
    if valor is None:
        return "(valor não informado)"
    try:
        valor_decimal = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return str(valor)

    negativo = valor_decimal < 0
    valor_decimal = abs(valor_decimal)
    inteiro, _, centavos = f"{valor_decimal:.2f}".partition(".")

    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    inteiro_fmt = ".".join(grupos)

    sinal = "-" if negativo else ""
    return f"{sinal}R$ {inteiro_fmt},{centavos}"


def formatar_moeda_erp(texto) -> str:
    """Valor monetário que já vem formatado como texto do ERP legado (ex.:
    'R$1.813,70' no campo `liquidacao`). Não reformatamos o número — só
    normalizamos o espaçamento. Vazio/None indica que o ERP ainda não
    calculou (contratos em novação/renovação)."""
    if not texto:
        return "(valor de quitação indisponível no momento — vou verificar e te retorno)"
    texto = str(texto).strip()
    if texto.startswith("R$") and not texto.startswith("R$ "):
        texto = "R$ " + texto[2:].lstrip()
    return texto


def _parse_valor_erp(texto):
    """Converte o texto de valor de quitação do ERP (ex.: 'R$ 1.813,70' ou
    'R$4.448,60') num `Decimal` para uso em somas do totalizador.
    `core.utils.parse_br_decimal` é um parser puro que espera só dígitos +
    separadores BR e QUEBRA com o prefixo "R$" -- por isso removemos antes
    qualquer caractere que não seja dígito/vírgula/ponto/sinal. Retorna
    `None` para texto vazio ou que não parseia (nunca levanta)."""
    if not texto:
        return None
    limpo = re.sub(r"[^\d,.\-]", "", str(texto))
    return parse_br_decimal(limpo)


def formatar_data(valor) -> str:
    """Formata uma data como 'dd/mm/aaaa'."""
    if valor is None:
        return "(data não informada)"
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


class _SafeDict(dict):
    """dict tolerante para `str.format_map`: uma chave ausente vira o
    próprio placeholder literal (ex.: '{nome}') em vez de lançar KeyError —
    um template mal editado no painel (pelo dono) não pode derrubar o envio
    da mensagem."""

    def __missing__(self, key):
        logger.warning("render_template: placeholder desconhecido '%s' no template", key)
        return "{" + key + "}"


def render_template(tpl: str, **ctx) -> str:
    """Renderiza um template `MensagensConfig.tpl_*`/`msg_*` com
    `format_map` tolerante a placeholders desconhecidos (loga warning e
    preserva o texto em vez de explodir)."""
    if not tpl:
        return ""
    try:
        return tpl.format_map(_SafeDict(**ctx))
    except Exception:  # noqa: BLE001 - template editável pelo dono nunca pode quebrar o turno
        logger.exception("render_template: falha inesperada ao renderizar template")
        return tpl


def _prazo_mais_proximo(prazo_dias: int) -> int:
    """Mapeia um prazo arbitrário para o campo `vlr_renovacao_<prazo>`
    disponível mais próximo (30/60/90/120/150/180)."""
    return min(PRAZOS_RENOVACAO, key=lambda p: abs(p - prazo_dias))


def _somar_decimais(valores) -> Decimal:
    total = Decimal("0")
    for valor in valores:
        if valor is None:
            continue
        try:
            total += Decimal(str(valor))
        except (InvalidOperation, ValueError, TypeError):
            logger.warning("_somar_decimais: valor não numérico ignorado na soma: %r", valor)
    return total


def _montar_totalizador(info, contratos: list, ativos_map: dict, msgs, prazo=None) -> str:
    """Monta a mensagem de totalizador (soma + quantidade) para o bloco de
    `contratos` já reportado ao cliente (as linhas efetivamente enviadas).

    - valor_renovacao: soma `vlr_renovacao_{prazo}`.
    - valor_quitacao: soma `_parse_valor_erp(liquidacao)`, pulando
      indisponíveis (com aviso no sufixo); todos indisponíveis -> usa
      `tpl_totalizador_sem_valor`.
    - valor_parcela: soma `vlr_parcela` (a lista `contratos` já vem só com
      os parcelados -- ver `renderizar_infos_contrato`).
    - vencimento/lista_contratos/detalhe_contrato: sem valor numérico
      significativo -> `tpl_totalizador_sem_valor`.
    """
    qtd = len(contratos)

    if info == InfoContrato.VALOR_RENOVACAO:
        total = _somar_decimais(ativos_map[num].get(f"vlr_renovacao_{prazo}") for num in contratos)
        return render_template(msgs.tpl_totalizador, qtd=qtd, total=formatar_moeda(total))

    if info == InfoContrato.VALOR_QUITACAO:
        valores = []
        indisponiveis = 0
        for num in contratos:
            parsed = _parse_valor_erp(ativos_map[num].get("liquidacao"))
            if parsed is None:
                indisponiveis += 1
            else:
                valores.append(parsed)

        sufixo = ""
        if indisponiveis:
            sufixo = (
                f"\n(não somei {indisponiveis} contrato(s) com valor de quitação "
                "indisponível — vou verificar e te retorno)"
            )

        if not valores:
            return f"{render_template(msgs.tpl_totalizador_sem_valor, qtd=qtd)}{sufixo}"

        total = _somar_decimais(valores)
        return f"{render_template(msgs.tpl_totalizador, qtd=qtd, total=formatar_moeda(total))}{sufixo}"

    if info == InfoContrato.VALOR_PARCELA:
        total = _somar_decimais(ativos_map[num].get("vlr_parcela") for num in contratos)
        return render_template(msgs.tpl_totalizador, qtd=qtd, total=formatar_moeda(total))

    # vencimento / lista_contratos / detalhe_contrato: sem soma financeira.
    return render_template(msgs.tpl_totalizador_sem_valor, qtd=qtd)


def renderizar_infos_contrato(cliente, pedidos, msgs) -> list[str]:
    """Renderiza a resposta para `tipo_intencao=info_contrato` como uma
    LISTA de mensagens (fan-out): o chamador (`whatsapp.tasks._enviar_fila`)
    envia cada item como uma mensagem WhatsApp separada, com pausa entre
    elas.

    Por `InfoContratoPedido` (uma por informação distinta pedida): 1
    contrato reportado -> lista com só a linha; 2+ -> intro
    (`tpl_lista_header`) + 1 linha por contrato + totalizador
    (`tpl_totalizador`/`tpl_totalizador_sem_valor`, soma + quantidade).
    `tpl_lista_footer` não é mais usado neste fluxo (fechamento incorporado
    ao totalizador).

    Todos os valores citados vêm do banco (nunca da IA): contratos ativos
    são relidos aqui via `_contratos_ativos_values`. Contratos citados que
    não estão entre os ativos do cliente são ignorados silenciosamente (a
    IA já é instruída a nunca inventar números fora da lista fornecida)."""
    from .tasks import _contratos_ativos_values  # import local: evita import circular no carregamento do módulo

    if not cliente:
        return [msgs.msg_sem_contratos_ativos]

    ativos = _contratos_ativos_values(cliente)
    if not ativos:
        return [msgs.msg_sem_contratos_ativos]

    ativos_map = {c["contrato"]: c for c in ativos}
    primeiro_nome = (cliente.nome or "").split()[0] if getattr(cliente, "nome", "") else ""

    mensagens = []
    for pedido in pedidos:
        if pedido.contratos:
            alvo = [n for n in pedido.contratos if n in ativos_map]
        else:
            alvo = list(ativos_map.keys())
        if not alvo:
            continue

        linhas = []
        contratos_incluidos = []
        prazo = None

        if pedido.info == InfoContrato.VENCIMENTO:
            for num in alvo:
                c = ativos_map[num]
                linhas.append(render_template(
                    msgs.tpl_contrato_vencimento,
                    contrato=c["contrato"],
                    vencimento=formatar_data(c["data_vencimento"]),
                ))
                contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.VALOR_RENOVACAO:
            prazo_informado = pedido.prazo_dias is not None
            prazo = _prazo_mais_proximo(pedido.prazo_dias or 30)
            for num in alvo:
                c = ativos_map[num]
                linha = render_template(
                    msgs.tpl_contrato_renovacao,
                    contrato=c["contrato"],
                    prazo_dias=prazo,
                    valor_renovacao=formatar_moeda(c.get(f"vlr_renovacao_{prazo}")),
                    vencimento=formatar_data(c["data_vencimento"]),
                )
                if not prazo_informado:
                    linha = f"{linha} (prazo padrão de 30 dias)"
                linhas.append(linha)
                contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.VALOR_QUITACAO:
            for num in alvo:
                c = ativos_map[num]
                linhas.append(render_template(
                    msgs.tpl_contrato_quitacao,
                    contrato=c["contrato"],
                    valor_quitacao=formatar_moeda_erp(c.get("liquidacao")),
                    vencimento=formatar_data(c["data_vencimento"]),
                ))
                contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.VALOR_PARCELA:
            for num in alvo:
                c = ativos_map[num]
                if not c.get("parcelado"):
                    continue
                linhas.append(render_template(
                    msgs.tpl_contrato_parcela,
                    contrato=c["contrato"],
                    valor_parcela=formatar_moeda(c.get("vlr_parcela")),
                ))
                contratos_incluidos.append(num)

        elif pedido.info in (InfoContrato.LISTA_CONTRATOS, InfoContrato.DETALHE_CONTRATO):
            for num in alvo:
                c = ativos_map[num]
                linhas.append(render_template(
                    msgs.tpl_contrato_resumo,
                    contrato=c["contrato"],
                    vencimento=formatar_data(c["data_vencimento"]),
                    valor_emprestimo=formatar_moeda(c.get("vlr_emprestimo")),
                ))
                contratos_incluidos.append(num)

        if not linhas:
            continue

        if len(linhas) == 1:
            mensagens.append(linhas[0])
            continue

        intro = render_template(msgs.tpl_lista_header, nome=primeiro_nome, qtd=len(linhas))
        totalizador = _montar_totalizador(pedido.info, contratos_incluidos, ativos_map, msgs, prazo=prazo)
        mensagens.append(intro)
        mensagens.extend(linhas)
        mensagens.append(totalizador)

    if not mensagens:
        return [msgs.msg_sem_contratos_ativos]

    return mensagens
