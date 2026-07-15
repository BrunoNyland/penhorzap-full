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
    "texto 🙏 Pode escrever sua dúvida que um atendente vai te responder?"
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
- solicitacoes: um item por ação de pagamento (renovar/quitar/parcela), com
  contratos citados (vazio = todos) e prazo_dias para renovar.
  pronto_para_criar_solicitacao=true só quando ação, contratos (ou "todos") e
  prazo (para renovação) estiverem claros na conversa.
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
"""
