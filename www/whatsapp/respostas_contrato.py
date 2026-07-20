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

from django.utils import timezone

from core.utils import parse_br_decimal
from ia.schemas import CampoValor, InfoContrato

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


def formatar_peso(valor) -> str:
    """Formata o campo `ContratoPenhor.peso` (Decimal, gramas) como
    '16,30 g', mesmo padrão de `formatar_moeda` sem depender do locale do
    SO. `None` indica que o app de avaliação não registrou peso."""
    if valor is None:
        return "(peso não informado)"
    try:
        valor_decimal = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return str(valor)
    return f"{formatar_moeda(valor_decimal).replace('R$ ', '')} g"


_RE_PESO_LOTE = re.compile(r",?\s*PESO\s*LOTE:\s*[\d.,]+\s*G\s*\([^)]*\)", re.IGNORECASE)


def _limpar_peso_do_laudo(texto) -> str:
    """Remove do texto livre de `laudo` (importado do ERP) o trecho
    redundante de peso (ex.: ', PESO LOTE: 16,30G (DEZESSEIS GRAMAS E
    TRINTA CENTIGRAMAS)') -- o peso já é exibido em linha própria a partir
    do campo `ContratoPenhor.peso`, já limpo no banco. Tolerante: se o
    padrão não for encontrado, devolve o texto original sem alteração
    (nunca levanta)."""
    if not texto:
        return texto
    limpo = _RE_PESO_LOTE.sub("", str(texto))
    limpo = re.sub(r"\s*;\s*$", "", limpo)
    limpo = re.sub(r"\s{2,}", " ", limpo)
    return limpo.strip()


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


def _montar_totalizador_geral(contratos: list, ativos_map: dict, msgs) -> str:
    """Totalizador financeiro geral -- substitui a antiga contagem simples
    ('são N contratos ao todo') nos casos em que não há um único valor
    numérico específico pedido pelo cliente (ex.: laudo, lista de
    contratos, vencimento, ou renovação sem prazo definido): soma
    `vlr_avaliacao`, `vlr_emprestimo` e `vlr_renovacao_{prazo}` (por prazo,
    só os prazos com algum dado disponível entre os `contratos`)."""
    qtd = len(contratos)
    total_avaliacao = _somar_decimais(ativos_map[num].get("vlr_avaliacao") for num in contratos)
    total_emprestimo = _somar_decimais(ativos_map[num].get("vlr_emprestimo") for num in contratos)

    linhas_prazo = []
    for prazo in PRAZOS_RENOVACAO:
        valores = [
            ativos_map[num].get(f"vlr_renovacao_{prazo}")
            for num in contratos
            if ativos_map[num].get(f"vlr_renovacao_{prazo}") is not None
        ]
        if valores:
            linhas_prazo.append(f"• {prazo} dias: {formatar_moeda(_somar_decimais(valores))}")

    renovacoes = ""
    if linhas_prazo:
        renovacoes = "\n🔄 Renovação total por prazo:\n" + "\n".join(linhas_prazo)

    return render_template(
        msgs.tpl_totalizador_geral,
        qtd=qtd,
        total_avaliacao=formatar_moeda(total_avaliacao),
        total_emprestimo=formatar_moeda(total_emprestimo),
        renovacoes=renovacoes,
    )


def _montar_totalizador(info, contratos: list, ativos_map: dict, msgs, prazo=None) -> str:
    """Monta a mensagem de totalizador (soma + quantidade) para o bloco de
    `contratos` já reportado ao cliente (as linhas efetivamente enviadas).

    - valor_renovacao: soma `vlr_renovacao_{prazo}`; sem prazo definido ->
      totalizador geral (breakdown por prazo já cobre o caso).
    - valor_quitacao: soma `_parse_valor_erp(liquidacao)`, pulando
      indisponíveis (com aviso no sufixo); todos indisponíveis -> usa o
      totalizador geral.
    - valor_parcela: soma `vlr_parcela` (a lista `contratos` já vem só com
      os parcelados -- ver `renderizar_infos_contrato`).
    - vencimento/lista_contratos/detalhe_contrato: sem valor numérico
      significativo -> totalizador geral.
    """
    qtd = len(contratos)

    if info == InfoContrato.VALOR_RENOVACAO:
        if prazo is None:
            return _montar_totalizador_geral(contratos, ativos_map, msgs)
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
            return f"{_montar_totalizador_geral(contratos, ativos_map, msgs)}{sufixo}"

        total = _somar_decimais(valores)
        return (
            f"{render_template(msgs.tpl_totalizador, qtd=qtd, total=formatar_moeda(total))}{sufixo}"
        )

    if info == InfoContrato.VALOR_PARCELA:
        total = _somar_decimais(ativos_map[num].get("vlr_parcela") for num in contratos)
        return render_template(msgs.tpl_totalizador, qtd=qtd, total=formatar_moeda(total))

    # vencimento / lista_contratos / detalhe_contrato: sem soma financeira.
    return _montar_totalizador_geral(contratos, ativos_map, msgs)


_INFOS_NUMERICOS = (
    InfoContrato.VALOR_RENOVACAO,
    InfoContrato.VALOR_QUITACAO,
    InfoContrato.VALOR_PARCELA,
)

_CAMPO_VALOR_DB = {
    CampoValor.EMPRESTIMO: "vlr_emprestimo",
    CampoValor.AVALIACAO: "vlr_avaliacao",
}

_INTRO_TPL_ATTR = {
    InfoContrato.VENCIMENTO: "tpl_intro_vencimento",
    InfoContrato.VALOR_RENOVACAO: "tpl_intro_renovacao",
    InfoContrato.VALOR_QUITACAO: "tpl_intro_quitacao",
    InfoContrato.VALOR_PARCELA: "tpl_intro_parcela",
    InfoContrato.LISTA_CONTRATOS: "tpl_intro_lista",
    InfoContrato.DETALHE_CONTRATO: "tpl_intro_lista",
    InfoContrato.LAUDO: "tpl_intro_laudo",
}


def _resolver_alvo(pedido, ativos_map: dict) -> list[str]:
    """Contratos-alvo do pedido: os citados (ou todos, se nenhum citado),
    com `filtro_vencido`/`filtro_valor_min`/`filtro_valor_max` aplicados.
    `filtro_valor_campo` ambíguo (min/max setados sem campo definido) não é
    resolvido aqui -- o dispatch (`whatsapp.tasks`) já deve suprimir esse
    pedido e perguntar ao cliente antes de chegar neste ponto; se algo
    escapar até aqui, o filtro de valor é ignorado (nunca levanta)."""
    if pedido.contratos:
        alvo = [n for n in pedido.contratos if n in ativos_map]
    else:
        alvo = list(ativos_map.keys())

    if pedido.filtro_vencido:
        hoje = timezone.localdate()
        alvo = [
            n
            for n in alvo
            if ativos_map[n].get("data_vencimento") and ativos_map[n]["data_vencimento"] < hoje
        ]

    tem_filtro_valor = pedido.filtro_valor_min is not None or pedido.filtro_valor_max is not None
    if tem_filtro_valor and pedido.filtro_valor_campo is not None:
        campo = _CAMPO_VALOR_DB[pedido.filtro_valor_campo]

        def _dentro_da_faixa(num):
            valor = ativos_map[num].get(campo)
            if valor is None:
                return False
            if pedido.filtro_valor_min is not None and valor < Decimal(
                str(pedido.filtro_valor_min)
            ):
                return False
            if pedido.filtro_valor_max is not None and valor > Decimal(
                str(pedido.filtro_valor_max)
            ):
                return False
            return True

        alvo = [n for n in alvo if _dentro_da_faixa(n)]

    return alvo


def renderizar_infos_contrato(cliente, pedidos, msgs) -> list[str]:
    """Renderiza a resposta para `infos_contrato` como uma LISTA de
    mensagens (fan-out): o chamador (`whatsapp.tasks._enviar_fila`) envia
    cada item como uma mensagem WhatsApp separada, com pausa entre elas.

    Tipos financeiros (`valor_renovacao`/`valor_quitacao`/`valor_parcela`)
    com 2+ contratos e `detalhado=False` (padrão) respondem SÓ com o
    totalizador -- sem listar contrato por contrato -- a menos que o
    cliente peça detalhado explicitamente. `filtro_vencido`/
    `filtro_valor_min`/`filtro_valor_max` (via `_resolver_alvo`) restringem
    quais contratos entram no pedido antes de tudo o mais.

    Para os demais casos, mescla POR CONTRATO em vez de por
    `InfoContratoPedido`: se o lote pediu mais de um tipo de dado (ex.:
    `lista_contratos` + `laudo`), cada contrato recebe UMA mensagem só com
    todas as linhas pedidas para ele. 1 contrato no total -> mensagem única
    mesclada, sem intro/totalizador; 2+ -> intro (específico do tipo
    pedido, ou `tpl_lista_header` genérico quando 2+ tipos diferentes estão
    misturados) + 1 mensagem mesclada por contrato + totalizador(es).

    Todos os valores citados vêm do banco (nunca da IA): contratos ativos
    são relidos aqui via `_contratos_ativos_values`. Contratos citados que
    não estão entre os ativos do cliente são ignorados silenciosamente (a
    IA já é instruída a nunca inventar números fora da lista fornecida)."""
    from .tasks import (
        _contratos_ativos_values,  # import local: evita import circular no carregamento do módulo
    )

    if not cliente:
        return [msgs.msg_sem_contratos_ativos]

    ativos = _contratos_ativos_values(cliente)
    if not ativos:
        return [msgs.msg_sem_contratos_ativos]

    ativos_map = {c["contrato"]: c for c in ativos}

    linhas_por_contrato: dict[str, list[str]] = {}
    totalizadores_numericos: list[str] = []
    tipos_com_linhas: set = set()
    existe_nao_numerico = False

    for pedido in pedidos:
        alvo = _resolver_alvo(pedido, ativos_map)
        if not alvo:
            continue

        eh_numerico = pedido.info in _INFOS_NUMERICOS

        if eh_numerico and not pedido.detalhado:
            # Resumo (padrão): só o totalizador, sem listar cada contrato --
            # mas só quando sobra mais de 1 contrato depois dos filtros
            # (parcela já restrita aos parcelados); com 0 ou 1, cai pro
            # caminho normal abaixo (linha direta, sem totalizer redundante).
            prazo = None
            contratos_resumo = alvo
            if pedido.info == InfoContrato.VALOR_RENOVACAO and pedido.prazo_dias is not None:
                prazo = _prazo_mais_proximo(pedido.prazo_dias)
            elif pedido.info == InfoContrato.VALOR_PARCELA:
                contratos_resumo = [n for n in alvo if ativos_map[n].get("parcelado")]
            if len(contratos_resumo) > 1:
                totalizadores_numericos.append(
                    _montar_totalizador(
                        pedido.info, contratos_resumo, ativos_map, msgs, prazo=prazo
                    )
                )
                continue

        linha_por_num: dict[str, str] = {}
        contratos_incluidos = []
        prazo = None

        if pedido.info == InfoContrato.VENCIMENTO:
            for num in alvo:
                c = ativos_map[num]
                linha_por_num[num] = render_template(
                    msgs.tpl_contrato_vencimento,
                    contrato=c["contrato"],
                    vencimento=formatar_data(c["data_vencimento"]),
                )
                contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.VALOR_RENOVACAO:
            prazo_informado = pedido.prazo_dias is not None
            if prazo_informado:
                prazo = _prazo_mais_proximo(pedido.prazo_dias)
                for num in alvo:
                    c = ativos_map[num]
                    linha_venc = render_template(
                        msgs.tpl_contrato_vencimento,
                        contrato=c["contrato"],
                        vencimento=formatar_data(c["data_vencimento"]),
                    )
                    linha_renov = render_template(
                        msgs.tpl_contrato_renovacao,
                        contrato=c["contrato"],
                        prazo_dias=prazo,
                        valor_renovacao=formatar_moeda(c.get(f"vlr_renovacao_{prazo}")),
                        vencimento=formatar_data(c["data_vencimento"]),
                    )
                    linha_por_num[num] = f"{linha_venc}\n{linha_renov}"
                    contratos_incluidos.append(num)
            else:
                # Se não foi informado um prazo específico, exibe todas as opções do contrato
                # agrupadas em uma mensagem única por contrato, usando o template tpl_contrato_renovacao.
                for num in alvo:
                    c = ativos_map[num]
                    linhas_contrato = [
                        render_template(
                            msgs.tpl_contrato_vencimento,
                            contrato=c["contrato"],
                            vencimento=formatar_data(c["data_vencimento"]),
                        )
                    ]
                    for p in PRAZOS_RENOVACAO:
                        val = c.get(f"vlr_renovacao_{p}")
                        if val is not None:
                            linha = render_template(
                                msgs.tpl_contrato_renovacao,
                                contrato=c["contrato"],
                                prazo_dias=p,
                                valor_renovacao=formatar_moeda(val),
                                vencimento=formatar_data(c["data_vencimento"]),
                            )
                            linhas_contrato.append(linha)

                    if len(linhas_contrato) > 1:
                        linha_por_num[num] = "\n".join(linhas_contrato)
                    else:
                        # Se não tem nenhum valor de renovação, mostra o default de 30 dias
                        linha_venc = render_template(
                            msgs.tpl_contrato_vencimento,
                            contrato=c["contrato"],
                            vencimento=formatar_data(c["data_vencimento"]),
                        )
                        linha_renov = render_template(
                            msgs.tpl_contrato_renovacao,
                            contrato=c["contrato"],
                            prazo_dias=30,
                            valor_renovacao=formatar_moeda(None),
                            vencimento=formatar_data(c["data_vencimento"]),
                        )
                        linha_por_num[num] = f"{linha_venc}\n{linha_renov}"
                    contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.VALOR_QUITACAO:
            for num in alvo:
                c = ativos_map[num]
                linha_venc = render_template(
                    msgs.tpl_contrato_vencimento,
                    contrato=c["contrato"],
                    vencimento=formatar_data(c["data_vencimento"]),
                )
                linha_quit = render_template(
                    msgs.tpl_contrato_quitacao,
                    contrato=c["contrato"],
                    valor_quitacao=formatar_moeda_erp(c.get("liquidacao")),
                    vencimento=formatar_data(c["data_vencimento"]),
                )
                linha_por_num[num] = f"{linha_venc}\n{linha_quit}"
                contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.VALOR_PARCELA:
            for num in alvo:
                c = ativos_map[num]
                if not c.get("parcelado"):
                    continue
                linha_por_num[num] = render_template(
                    msgs.tpl_contrato_parcela,
                    contrato=c["contrato"],
                    valor_parcela=formatar_moeda(c.get("vlr_parcela")),
                )
                contratos_incluidos.append(num)

        elif pedido.info in (InfoContrato.LISTA_CONTRATOS, InfoContrato.DETALHE_CONTRATO):
            for num in alvo:
                c = ativos_map[num]
                linha_por_num[num] = render_template(
                    msgs.tpl_contrato_resumo,
                    contrato=c["contrato"],
                    vencimento=formatar_data(c["data_vencimento"]),
                    valor_emprestimo=formatar_moeda(c.get("vlr_emprestimo")),
                )
                contratos_incluidos.append(num)

        elif pedido.info == InfoContrato.LAUDO:
            for num in alvo:
                c = ativos_map[num]
                linha_por_num[num] = render_template(
                    msgs.tpl_contrato_laudo,
                    contrato=c["contrato"],
                    peso=formatar_peso(c.get("peso")),
                    valor_avaliacao=formatar_moeda(c.get("vlr_avaliacao")),
                    laudo=_limpar_peso_do_laudo(c.get("laudo") or "Laudo não disponível"),
                )
                contratos_incluidos.append(num)

        if not linha_por_num:
            continue

        for num, texto in linha_por_num.items():
            linhas_por_contrato.setdefault(num, []).append(texto)
        tipos_com_linhas.add(pedido.info)

        if eh_numerico:
            if len(contratos_incluidos) > 1:
                totalizadores_numericos.append(
                    _montar_totalizador(
                        pedido.info, contratos_incluidos, ativos_map, msgs, prazo=prazo
                    )
                )
        else:
            existe_nao_numerico = True

    if not linhas_por_contrato and not totalizadores_numericos:
        return [msgs.msg_sem_contratos_ativos]

    mensagens: list[str] = []

    # Ordem canônica do banco (via `ativos_map`), não a ordem dos pedidos.
    contratos_finais = [num for num in ativos_map if num in linhas_por_contrato]

    if contratos_finais:
        if len(contratos_finais) == 1:
            mensagens.append("\n".join(linhas_por_contrato[contratos_finais[0]]))
        else:
            if len(tipos_com_linhas) == 1:
                intro_tpl = getattr(msgs, _INTRO_TPL_ATTR[next(iter(tipos_com_linhas))])
            else:
                intro_tpl = msgs.tpl_lista_header
            mensagens.append(render_template(intro_tpl, qtd=len(contratos_finais)))
            for num in contratos_finais:
                mensagens.append("\n".join(linhas_por_contrato[num]))

    if totalizadores_numericos:
        mensagens.extend(totalizadores_numericos)
    elif existe_nao_numerico and len(contratos_finais) > 1:
        mensagens.append(_montar_totalizador_geral(contratos_finais, ativos_map, msgs))

    return mensagens
