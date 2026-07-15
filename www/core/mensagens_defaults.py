"""Default texts for MensagensConfig (persona em 1ª pessoa) e prompt do Gemini.

Fonte única dos valores padrão: core/models.py usa como `default=` dos campos,
ia/services.py usa no fallback, e painel/views.py usa no botão "Restaurar
padrão" de cada campo.
"""

# --- Saudação / triagem de contato -----------------------------------------

DEFAULT_MSG_SAUDACAO = "{saudacao}! Como posso ajudar hoje?"
DEFAULT_MSG_CADASTRO_NAO_LOCALIZADO = (
    "Oi! Não achei seu número aqui no meu cadastro. Assim que eu tiver um "
    "tempinho eu verifico pra você e já te retorno, combinado?"
)
DEFAULT_MSG_INSISTIU_HUMANO = (
    "Assim que possível estarei verificando pra você, tá bom?"
)

# --- Verificação de CPF ------------------------------------------------------

DEFAULT_MSG_PEDIR_CPF = (
    "Pra eu te passar informações de contrato ou emitir boleto, me confirma "
    "o seu CPF completo?"
)
DEFAULT_MSG_CPF_INVALIDO = (
    "Hmm, esse CPF parece não estar certo não. Dá uma conferida e me manda "
    "de novo o seu CPF completo?"
)
DEFAULT_MSG_CPF_NAO_BATE = (
    "Esse CPF não bate com o que tenho aqui pra este número. Você pode "
    "confirmar pra mim o CPF certo do titular do contrato?"
)
DEFAULT_MSG_VERIFICACAO_OK = "Perfeito, confirmado! Me diz então, em que posso te ajudar hoje?"
DEFAULT_MSG_VERIFICACAO_FALHOU = (
    "Hmm, não bateu com o que tenho aqui no cadastro. Dá uma conferida e me "
    "manda de novo os 3 últimos dígitos do seu CPF?"
)

# --- Informações / FAQ / database desatualizada ------------------------------

DEFAULT_MSG_SEM_INFO_FAQ = (
    "Boa! Me passa o seu CPF que assim que eu tiver um tempinho eu verifico "
    "isso pra você e te retorno."
)
DEFAULT_MSG_DB_DESATUALIZADA = (
    "Me confirma o seu CPF? Assim que eu atualizar meus sistema aqui eu "
    "verifico certinho pra você e te retorno."
)
DEFAULT_MSG_SEM_CONTRATOS_ATIVOS = (
    "Pelo que vejo aqui, você não tem contratos ativos no momento. Se quiser "
    "qualquer coisa, é só me chamar!"
)

# --- Pagamento / boletos -----------------------------------------------------

DEFAULT_MSG_SOLICITACAO_CRIADA = (
    "Anotei tudo aqui! Já vou gerar o(s) boleto(s) e assim que estiverem "
    "prontos eu te mando por aqui mesmo, combinado?"
)
DEFAULT_MSG_BOLETO_INTRO = (
    "Prontinho, segue o boleto que você pediu 😉 Logo abaixo te mando também "
    "o código de barras pra facilitar."
)
DEFAULT_MSG_RENOVACAO_PROXIMO_VENCIMENTO = (
    "Lembrando que o boleto de renovação é pra pagar hoje, tá? Depois de "
    "pago, o próximo vencimento cai em {proximo_vencimento}."
)
DEFAULT_MSG_QUITACAO_GARANTIA = (
    "Como você está quitando, suas garantias ficam liberadas pra resgate a "
    "partir de {data_resgate}, beleza?"
)
DEFAULT_MSG_SEGUNDA_VIA_CONFIRMA = (
    "Localizei o boleto anterior. Pra eu te mandar de novo, me confirma: é "
    "do contrato {contratos}, {tipo}, certo?"
)

DEFAULT_MSG_NEUTRA_PADRAO = (
    "Recebi sua mensagem! Assim que eu tiver um tempinho eu dou uma olhada "
    "com calma e te respondo, tá bom?"
)

# --- Templates v2 (identificação por telefone / respostas de contrato) ------

DEFAULT_TPL_SAUDACAO_CLIENTE = (
    "{saudacao}, {nome}! 😊 Aqui é o atendimento da PenhorZap. Como posso "
    "te ajudar?"
)
DEFAULT_TPL_CONTRATO_VENCIMENTO = "📄 Contrato {contrato}: vencimento em {vencimento}."
DEFAULT_TPL_CONTRATO_RENOVACAO = (
    "🔄 Contrato {contrato}: renovação por {prazo_dias} dias = "
    "{valor_renovacao} (vencimento atual: {vencimento})."
)
DEFAULT_TPL_CONTRATO_QUITACAO = (
    "✅ Contrato {contrato}: valor para quitação = {valor_quitacao} "
    "(vencimento: {vencimento})."
)
DEFAULT_TPL_CONTRATO_PARCELA = "💳 Contrato {contrato}: valor da parcela = {valor_parcela}."
DEFAULT_TPL_CONTRATO_RESUMO = (
    "📄 Contrato {contrato} — vencimento {vencimento} — valor do empréstimo "
    "{valor_emprestimo}."
)
DEFAULT_TPL_LISTA_HEADER = "{nome}, você tem {qtd} contrato(s) ativo(s):"
DEFAULT_TPL_LISTA_FOOTER = "Se precisar de mais alguma informação, é só falar!"
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
DEFAULT_MSG_INFO_NEGADA_DESCONHECIDO = (
    "Por segurança, as informações do seu contrato constam no próprio "
    "boleto. Quer que eu gere o boleto pra você?"
)
DEFAULT_MSG_MIDIA_NAO_SUPORTADA = (
    "Recebi seu áudio/vídeo, mas por aqui eu só consigo ler mensagens de "
    "texto 🙏 Pode escrever sua dúvida que um atendente vai te responder?"
)

DEFAULT_SYSTEM_PROMPT = """\
Você é um CLASSIFICADOR de mensagens de clientes de uma casa de penhores no
WhatsApp. Você NUNCA escreve resposta ao cliente — apenas preenche o schema
JSON pedido. Todo texto que o cliente recebe nasce de templates fixos em
Python, fora do seu controle.

Você recebe: a mensagem atual, o histórico recente, um bloco ESTADO
(identificado, database_atualizada, contato_tipo — apenas contexto; as
regras de acesso são aplicadas pelo sistema, não por você), a lista de
contratos ativos do cliente (número, vencimento, parcelado — sem valores) e
a lista de FAQs (id + pergunta).

tipo_intencao:
- saudacao: cumprimento sem pedido concreto.
- duvida_geral: pergunta que não depende dos contratos do cliente (horário,
  endereço, juros, como funciona...). Se corresponder claramente a uma FAQ,
  preencha faq_id. Se NÃO houver FAQ correspondente, deixe faq_id nulo e
  preencha pergunta_sugerida_faq com a pergunta reescrita de forma curta e
  genérica.
- info_contrato: o cliente quer um dado dos contratos DELE. Preencha
  infos_contrato, um item por informação: vencimento | valor_renovacao
  (prazo_dias se citado) | valor_quitacao | valor_parcela | lista_contratos
  ("quais contratos eu tenho?") | detalhe_contrato. Em contratos, liste os
  números citados; vazio = todos.
- pagamento: quer renovar/quitar/pagar parcela. Preencha solicitacoes (uma
  por ação: tipo + contratos + prazo_dias para renovar; contratos vazio =
  todos). pronto_para_criar_solicitacao=true só quando a ação, os contratos
  (ou "todos") e o prazo (para renovação) estiverem claros na conversa.
- segunda_via: pedir reenvio de boleto já solicitado antes.
- outro: nada acima.

Regras:
1. Nunca invente números de contrato: use apenas os da lista fornecida.
2. Se o cliente insistir sem obter resposta ou demonstrar irritação/urgência,
   marque precisa_humano=true.
3. Na dúvida entre duvida_geral e info_contrato: se a resposta depende dos
   dados DO cliente, é info_contrato.
"""
