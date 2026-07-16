"""Default texts for MensagensConfig (persona em 1ª pessoa) e prompt do Gemini.

Fonte única dos valores padrão: core/models.py usa como `default=` dos campos,
ia/services.py usa no fallback, e painel/views.py usa no botão "Restaurar
padrão" de cada campo.
"""

# --- Saudação / triagem de contato -----------------------------------------

DEFAULT_MSG_SAUDACAO = "{saudacao}! Como posso ajudar?"
DEFAULT_MSG_CADASTRO_NAO_LOCALIZADO = (
    "Oi! Não achei seu número aqui no meu cadastro. Assim que eu tiver um "
    "tempinho eu verifico pra você e já te retorno."
)

# --- Verificação de CPF ------------------------------------------------------

DEFAULT_MSG_PEDIR_CPF = "Me informe seu CPF por gentileza, que já verifico para você."
DEFAULT_MSG_CPF_INVALIDO = (
    "O CPF que vc me passou está inválido 🤦‍♂️ Dá uma conferida e me manda "
    "novamente por favor 😁🙏"
)
DEFAULT_MSG_CPF_NAO_BATE = (
    "Esse CPF não bate com o que tenho aqui pra este número. Você pode "
    "confirmar pra mim o CPF certo do titular do contrato?"
)
# --- Informações / FAQ / database desatualizada ------------------------------

DEFAULT_MSG_DB_DESATUALIZADA = (
    "*Mensagem automática:* Oi. Estou ocupado no momento. Mas assim que eu "
    "tiver um tempinho eu te verifico pra vc. 🤝"
)
DEFAULT_MSG_SEM_CONTRATOS_ATIVOS = (
    "Pelo que verifiquei aqui no sistema vc não tem contratos ativos no momento."
)

# --- Pagamento / boletos -----------------------------------------------------

DEFAULT_MSG_SOLICITACAO_CRIADA = (
    "Vou gerar o(s) boleto(s) e daqui a pouco eu te envio aqui mesmo."
)
DEFAULT_MSG_BOLETO_INTRO = (
    "Prontinho, segue o boleto que você pediu. 😁👍 Logo abaixo te mando também "
    "o código de barras pra facilitar."
)
DEFAULT_MSG_RENOVACAO_PROXIMO_VENCIMENTO = (
    "Lembrando que o boleto só vale para hoje, ok? Depois de pago, o próximo "
    "vencimento será {proximo_vencimento}."
)
DEFAULT_MSG_QUITACAO_GARANTIA = (
    "Pagando hoje o boleto, vc pode vir resgatar a partir de 📆{data_resgate} "
    "as 🕜11hrs."
)
DEFAULT_MSG_SEGUNDA_VIA_CONFIRMA = (
    "Localizei o boleto anterior. Pra eu te mandar de novo, me confirma: é "
    "do contrato {contratos}, {tipo}, certo?"
)

DEFAULT_MSG_NEUTRA_PADRAO = (
    "*Mensagem automática:* Oi. Estou ocupado no momento. Mas assim que eu "
    "tiver um tempinho eu te verifico pra vc. 🤝"
)

# --- Templates v2 (identificação por telefone / respostas de contrato) ------

DEFAULT_TPL_SAUDACAO_CLIENTE = (
    "{saudacao}, {nome}! 😊 Como posso te ajudar?"
)
DEFAULT_TPL_CONTRATO_VENCIMENTO = "📄 *Contrato* {contrato}\n🗓️ *Vencimento*: {vencimento}."
DEFAULT_TPL_CONTRATO_RENOVACAO = "🔹Renovação {prazo_dias} dias: {valor_renovacao}"
DEFAULT_TPL_CONTRATO_QUITACAO = "🔸Liquidação: {valor_quitacao}"
DEFAULT_TPL_CONTRATO_PARCELA = "📄 *Contrato*: {contrato}\n💰 Valor das parcelas: {valor_parcela}"
DEFAULT_TPL_CONTRATO_RESUMO = (
    "📄 *Contrato*: {contrato}\n🗓️ *Vencimento*: {vencimento}\n💰 *Empréstimo*: {valor_emprestimo}"
)
DEFAULT_TPL_LISTA_HEADER = "{nome}, você tem {qtd} contrato(s) ativo(s):"
DEFAULT_TPL_TOTALIZADOR = (
    "📊 Resumo: {qtd} contrato(s), total de {total}. Se precisar de mais "
    "alguma informação, é só falar!"
)
DEFAULT_TPL_TOTALIZADOR_SEM_VALOR = (
    "São {qtd} contrato(s) ao todo. Se precisar de mais alguma informação, "
    "é só falar!"
)

DEFAULT_MSG_FALLBACK_SEM_RESPOSTA = (
    "Boa pergunta! Deixa eu verificar com calma e já te retorno por aqui "
    "mesmo, combinado?"
)
DEFAULT_MSG_DUVIDA_ANOTADA = (
    "Sobre {duvidas}: vou verificar com calma e te retorno por aqui mesmo, "
    "combinado? 🙂"
)
DEFAULT_MSG_INFO_NEGADA_DESCONHECIDO = (
    "Por segurança, as informações do seu contrato constam no próprio "
    "boleto. Quer que eu gere o boleto pra você?"
)
DEFAULT_MSG_MIDIA_NAO_SUPORTADA = (
    "Recebi seu áudio/vídeo, mas por aqui eu só consigo ler mensagens de "
    "texto 🙏 Pode escrever sua dúvida que já te respondo."
)

DEFAULT_SYSTEM_PROMPT = """\
Você é um CLASSIFICADOR de mensagens de clientes de uma casa de penhores no
WhatsApp. Você NUNCA escreve resposta ao cliente — apenas preenche o schema
JSON pedido. Todo texto que o cliente recebe nasce de templates fixos em
Python, fora do seu controle.

Você recebe: as MENSAGENS NÃO RESPONDIDAS do cliente (em ordem, pode ser mais
de uma), o histórico recente, um bloco ESTADO (identificado,
database_atualizada, contato_tipo — apenas contexto; as regras de acesso são
aplicadas pelo sistema, não por você), a lista de contratos ativos do cliente
(número, vencimento, parcelado — sem valores) e a lista de FAQs (id + pergunta).

TAREFA: identifique TODAS as solicitações presentes no lote, sem esquecer
nenhuma. Uma mensagem pode conter várias intenções ao mesmo tempo; preencha
todos os campos que se aplicarem:

- saudacao: true se o cliente cumprimentou neste lote.
- faq_ids: IDs de TODAS as FAQs que respondem perguntas do lote.
- infos_contrato: um item por dado de contrato pedido: vencimento |
  valor_renovacao (prazo_dias se citado) | valor_quitacao | valor_parcela |
  lista_contratos ("quais contratos eu tenho?") | detalhe_contrato. Em
  contratos, liste os números citados; vazio = todos.
- solicitacoes: um item por ação de pagamento (renovar/quitar/parcela/indefinido), com
  contratos citados (vazio = todos) e prazo_dias para renovar.
  Use "indefinido" se o cliente quer pagar/gerar boleto mas não especificou se
  quer renovar ou quitar ou pagar parcela.
  pronto_para_criar_solicitacao=true só quando a ação (renovar, quitar ou parcela
  definidas — NUNCA indefinido), contratos (ou "todos") e prazo (para renovação)
  estiverem claros na conversa.
- segunda_via: true se pediu reenvio de boleto já solicitado antes.
- duvidas_sem_faq: perguntas sem FAQ correspondente e que não dependem dos
  contratos do cliente, cada uma reescrita curta e genérica.
- precisa_humano: true se houver irritação, urgência, insistência sem resposta
  ou pedido fora do escopo.

Regras:
1. Nunca invente números de contrato: use apenas os da lista fornecida.
2. Um CPF digitado sozinho não é uma solicitação: ignore-o (o sistema já o
   validou).
3. Na dúvida entre duvidas_sem_faq e infos_contrato: se a resposta depende dos
   dados DO cliente, é infos_contrato.
4. Não repita ações já atendidas no histórico; classifique apenas o que está
   pendente nas mensagens não respondidas.
5. Se o lote não contém nenhum pedido (ex.: só "ok", "obrigado"), deixe tudo
   vazio/false.
6. Se o cliente pedir um boleto ou quiser pagar/gerar boleto de um ou mais contratos,
   mas não deixou claro se quer renovar, quitar ou pagar uma parcela, você deve gerar a
   solicitacao com tipo="indefinido" e definir pronto_para_criar_solicitacao=false.
"""
