from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TipoPagamento(str, Enum):
    RENOVAR = "renovar"
    QUITAR = "quitar"
    PARCELA = "parcela"
    INDEFINIDO = "indefinido"


class SolicitacaoDraft(BaseModel):
    tipo: TipoPagamento
    contratos: List[str] = Field(
        default_factory=list,
        description="Números de contrato citados/escolhidos. Lista VAZIA = todos os contratos ativos do cliente.",
    )
    prazo_dias: Optional[int] = Field(
        default=None,
        description="Para tipo=renovar: 30/60/90/120/150/180. None se o cliente não informou (sistema presume 30 e confirma).",
    )


class InfoContrato(str, Enum):
    VENCIMENTO = "vencimento"
    VALOR_RENOVACAO = "valor_renovacao"
    VALOR_QUITACAO = "valor_quitacao"
    VALOR_PARCELA = "valor_parcela"
    LISTA_CONTRATOS = "lista_contratos"
    DETALHE_CONTRATO = "detalhe_contrato"


class InfoContratoPedido(BaseModel):
    info: InfoContrato
    contratos: List[str] = Field(
        default_factory=list,
        description="Números de contrato citados pelo cliente. Vazio = todos os ativos.",
    )
    prazo_dias: Optional[int] = Field(
        default=None,
        description="Só para valor_renovacao: 30/60/90/120/150/180. None = não informado.",
    )


class ClassificacaoLote(BaseModel):
    """Schema multi-ação (Fase 2/WS-A v3): a Gemini classifica TODAS as
    solicitações presentes no LOTE de mensagens não respondidas do cliente
    de uma vez -- uma única mensagem pode conter várias intenções ao mesmo
    tempo (saudação + FAQ + pedido de contrato + pagamento...). Cada campo
    abaixo é preenchido de forma independente, sem exclusão mútua entre eles
    (substitui o `tipo_intencao` único de `ClassificacaoMensagem`)."""

    saudacao: bool = Field(
        default=False, description="True se o cliente cumprimentou neste lote."
    )
    faq_ids: List[int] = Field(
        default_factory=list,
        description="IDs de TODAS as FAQs cadastradas que respondem alguma pergunta do lote.",
    )
    infos_contrato: List[InfoContratoPedido] = Field(
        default_factory=list,
        description=(
            "Um item por dado de contrato pedido: vencimento | valor_renovacao "
            "(prazo_dias se citado) | valor_quitacao | valor_parcela | "
            "lista_contratos | detalhe_contrato."
        ),
    )
    solicitacoes: List[SolicitacaoDraft] = Field(
        default_factory=list,
        description="Um item por ação de pagamento distinta (renovar/quitar/parcela) presente no lote.",
    )
    pronto_para_criar_solicitacao: bool = Field(
        default=False,
        description=(
            "True quando TODOS os dados necessários das solicitações estão "
            "coletados (ação, contratos -- ou 'todos' -- e prazo definido p/ renovar)."
        ),
    )
    segunda_via: bool = Field(
        default=False,
        description="True se o cliente pediu reenvio de um boleto já solicitado antes.",
    )
    duvidas_sem_faq: List[str] = Field(
        default_factory=list,
        description="Perguntas do lote sem FAQ correspondente, cada uma reescrita curta e genérica.",
    )
    precisa_humano: bool = Field(
        default=False, description="True se um operador humano deve revisar/atuar antes de responder."
    )

    def nenhuma_acao(self) -> bool:
        """True quando o lote não gerou NENHUMA solicitação classificável
        (ex.: "ok", "obrigado") -- `precisa_humano` é ortogonal e não entra
        nesta checagem (marca revisão sem, por si só, contar como ação)."""
        return not (
            self.saudacao
            or self.faq_ids
            or self.infos_contrato
            or self.solicitacoes
            or self.segunda_via
            or self.duvidas_sem_faq
        )
