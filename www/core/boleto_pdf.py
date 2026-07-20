"""Geração do PDF do boleto a partir dos dados (linha digitável, valor,
vencimento etc.) — porta do que `brilhante/servicos/boleto.py` e
`brilhante/servicos/codigo_de_barras.py` já fazem no desktop, pro servidor
gerar o PDF sozinho a partir do JSON que o brilhante manda (ver
`api.views.SolicitacaoViewSet.boletos`), sem precisar mais receber o PDF
pronto.

Motor: mesmo template HTML (Jinja2) renderizado via wkhtmltopdf (pdfkit) e o
mesmo código de barras ITF (python-barcode) — mantém o boleto gerado aqui
visualmente idêntico ao que o brilhante já gerava localmente.
"""
import base64
import io
import os
from pathlib import Path

import pdfkit
from barcode import get_barcode_class
from barcode.writer import ImageWriter
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "templates" / "boleto"

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Logo da CAIXA embutido como data URI — mesmo valor usado em
# brilhante/servicos/boleto.py, pro boleto gerado aqui ficar idêntico.
LOGO_CAIXA_SRC = "data:image/jpg;base64, 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"  # noqa: E501


def _remover_simbolos_e_espacos(texto: str) -> str:
    return "".join(texto.split()).replace(".", "").replace("-", "")


def linha_digitavel_para_codigo_de_barras(linha: str) -> str:
    """Converte a linha digitável de um boleto no código de barras (44 dígitos).

    Idêntico a `brilhante.servicos.codigo_de_barras.linha_digitavel_para_codigo_de_barras`
    — ver lá o porquê (a linha digitável não é o código de barras, é uma
    reorganização dele em campos com DVs intercalados).
    """
    linha = _remover_simbolos_e_espacos(linha)

    if len(linha) == 44:
        return linha

    if len(linha) == 47:
        campo1 = linha[0:10]
        campo2 = linha[10:21]
        campo3 = linha[21:32]
        dv_geral = linha[32]
        fator_valor = linha[33:47]
        return (
            campo1[0:4]
            + dv_geral
            + fator_valor
            + campo1[4:9]
            + campo2[0:10]
            + campo3[0:10]
        )

    if len(linha) == 48:
        return linha[0:11] + linha[12:23] + linha[24:35] + linha[36:47]

    raise ValueError(f"Linha digitável com tamanho inesperado ({len(linha)} dígitos): {linha!r}")


def gerar_codigo_de_barra_boleto(linha_digitavel: str) -> str:
    """Gera o código de barras ITF do boleto (data URI base64), a partir da
    linha digitável — mesma técnica de
    `brilhante.servicos.codigo_de_barras.gerar_codigo_de_barra_boleto`."""
    num = linha_digitavel_para_codigo_de_barras(linha_digitavel)

    barcode_class = get_barcode_class("itf")
    codigo_de_barra = barcode_class(num, writer=ImageWriter())
    buffer = io.BytesIO()
    codigo_de_barra.write(buffer, options={"write_text": False, "font_size": 10, "module_height": 10})
    return f"data:image/png;base64, {base64.b64encode(buffer.getvalue()).decode('utf-8')}"


def get_wkhtmltopdf_config():
    """Configuração do pdfkit apontando pro binário do wkhtmltopdf no
    servidor Linux (instalado via `apt-get install wkhtmltopdf` — pré-requisito
    de infra, fora do escopo deste código). Path customizável via env
    `WKHTMLTOPDF_PATH` pra ambientes onde o binário fica em outro lugar."""
    path = os.environ.get("WKHTMLTOPDF_PATH", "/usr/bin/wkhtmltopdf")
    return pdfkit.configuration(wkhtmltopdf=path)


def make_html(dados: dict) -> str:
    """`dados` com as chaves linha_digitavel, numero_documento, nosso_numero,
    vencimento, valor, nome, cpf, endereco — mesmos 8 campos que o brilhante
    já extrai do SIPEN (ver `liquidacao_funcoes.py`/`renovacao_funcoes.py`)."""
    template = _env.get_template("boleto.html")
    return template.render(
        linha_digitavel=dados["linha_digitavel"],
        numero_documento=dados["numero_documento"],
        nosso_numero=dados["nosso_numero"],
        data=dados["vencimento"],
        valor=dados["valor"],
        nome=dados["nome"],
        cpf=dados["cpf"],
        endereco=dados.get("endereco", ""),
        logo_caixa_src=LOGO_CAIXA_SRC,
        codigo_barras_src=gerar_codigo_de_barra_boleto(dados["linha_digitavel"]),
    )


def gerar_boleto_pdf_bytes(dados: dict) -> bytes:
    """Renderiza o boleto (HTML + código de barras) e retorna os bytes do PDF
    pronto — usado por `SolicitacaoViewSet.boletos` pra gerar o `Boleto.arquivo`
    a partir dos dados recebidos do brilhante, em vez de receber o PDF pronto."""
    html = make_html(dados)
    options = {
        "zoom": 1.16,
        "margin-top": "0.1in",
        "margin-right": "0.1in",
        "margin-bottom": "0.1in",
        "margin-left": "0.1in",
    }
    return pdfkit.from_string(html, False, options=options, configuration=get_wkhtmltopdf_config())
