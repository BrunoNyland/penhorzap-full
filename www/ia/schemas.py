from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TipoIntencao(str, Enum):
    SAUDACAO = "saudacao"
    DUVIDA_GERAL = "duvida_geral"
    DUVIDA_ESPECIFICA = "duvida_especifica"
    PAGAMENTO = "pagamento"
    SEGUNDA_VIA = "segunda_via"
    OUTRO = "outro"


class TipoPagamento(str, Enum):
    RENOVAR = "renovar"
    QUITAR = "quitar"
    PARCELA = "parcela"


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


class IntencaoCliente(BaseModel):
    tipo_intencao: TipoIntencao
    cpf_extraido: Optional[str] = Field(
        default=None,
        description="CPF completo (somente dígitos) que o cliente digitou nesta mensagem, se houver.",
    )
    duvida_cliente: Optional[str] = Field(default=None, description="Texto resumido da dúvida, se aplicável.")
    resposta_faq: Optional[str] = Field(
        default=None, description="Se respondeu usando a FAQ, o texto da resposta usada (para auditoria)."
    )
    faq_id: Optional[int] = Field(
        default=None,
        description="Se a mensagem do cliente corresponder a uma FAQ cadastrada, preencha com o ID (número inteiro) da FAQ correspondente. Caso contrário, deixe null."
    )
    solicitacoes: List[SolicitacaoDraft] = Field(
        default_factory=list,
        description="Preencher quando tipo_intencao=pagamento. Uma entrada por ação distinta (ex.: quitar A + renovar B 60).",
    )
    pronto_para_criar_solicitacao: bool = Field(
        default=False,
        description="True quando TODOS os dados necessários estão coletados (cpf verificado, contratos definidos/assumíveis, prazo definido p/ renovar).",
    )
    resposta_sugerida: str = Field(description="Resposta em português a ser enviada ao cliente via WhatsApp.")
    precisa_humano: bool = Field(
        default=False, description="True se um operador humano deve revisar/atuar antes de responder."
    )
