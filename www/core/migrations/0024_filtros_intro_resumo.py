import logging

from django.db import migrations, models

logger = logging.getLogger("core.migrations.0024_filtros_intro_resumo")

PROMPT_ANTIGO = """\
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
  lista_contratos ("quais contratos eu tenho?") | detalhe_contrato | laudo ("quero ver o laudo do contrato", "qual a descrição da garantia/joias?"). Em
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

PROMPT_NOVO = """\
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
  lista_contratos ("quais contratos eu tenho?") | detalhe_contrato | laudo ("quero ver o laudo do contrato", "qual a descrição da garantia/joias?"). Em
  contratos, liste os números citados; vazio = todos.
  - detalhado: só para valor_renovacao/valor_quitacao/valor_parcela. true SÓ
    se o cliente pedir explicitamente para ver contrato por contrato,
    separado ou detalhado. Default false = o sistema prefere responder só
    com o total somado (não liste cada contrato à toa).
  - filtro_vencido: true se o cliente pedir só os contratos vencidos/em
    atraso.
  - filtro_valor_min / filtro_valor_max: quando o cliente pedir contratos
    "acima de X", "abaixo de X" ou "entre X e Y" reais, extraia o(s)
    número(s) citado(s).
  - filtro_valor_campo: "emprestimo" se o cliente falar do valor
    emprestado/valor do contrato; "avaliacao" se falar do valor da
    joia/avaliação. Deixe null se não ficar claro qual o cliente quer -- o
    sistema pergunta antes de filtrar.
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

TPL_LISTA_HEADER_ANTIGO = "{nome}, você tem {qtd} contrato(s) ativo(s):"
TPL_LISTA_HEADER_NOVO = "Segue as informações dos seus {qtd} contrato(s):"


def substituir_defaults_customizaveis(apps, schema_editor):
    MensagensConfig = apps.get_model("core", "MensagensConfig")
    config = MensagensConfig.objects.filter(pk=1).first()
    if config is None:
        return

    update_fields = []

    prompt_atual = (config.system_prompt or "").replace("\r\n", "\n")
    if prompt_atual == PROMPT_ANTIGO.replace("\r\n", "\n"):
        config.system_prompt = PROMPT_NOVO
        update_fields.append("system_prompt")
        logger.info("0024: system_prompt padrão substituído (filtros/detalhado/resumo).")
    else:
        logger.warning("0024: system_prompt salvo no banco é customizado -- NÃO foi substituído automaticamente.")

    if (config.tpl_lista_header or "").strip() == TPL_LISTA_HEADER_ANTIGO:
        config.tpl_lista_header = TPL_LISTA_HEADER_NOVO
        update_fields.append("tpl_lista_header")
        logger.info("0024: tpl_lista_header padrão substituído (sem nome do cliente).")
    else:
        logger.warning("0024: tpl_lista_header salvo no banco é customizado -- NÃO foi substituído automaticamente.")

    if update_fields:
        config.save(update_fields=update_fields)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_saudacao_com_pedido'),
    ]

    operations = [
        migrations.AddField(
            model_name='mensagensconfig',
            name='msg_pedir_campo_valor_filtro',
            field=models.TextField(default='Você quer filtrar pelo valor do empréstimo ou pelo valor de avaliação da joia?', help_text="Pergunta quando o cliente pede um filtro de valor (ex.: 'acima de 10 mil') sem deixar claro se é valor do empréstimo ou de avaliação."),
        ),
        migrations.AddField(
            model_name='mensagensconfig',
            name='tpl_intro_laudo',
            field=models.TextField(default='Segue os laudos dos seus contratos:'),
        ),
        migrations.AddField(
            model_name='mensagensconfig',
            name='tpl_intro_lista',
            field=models.TextField(default='Segue a lista dos seus contratos:'),
        ),
        migrations.AddField(
            model_name='mensagensconfig',
            name='tpl_intro_parcela',
            field=models.TextField(default='Segue a lista dos seus contratos com os valores de parcela:'),
        ),
        migrations.AddField(
            model_name='mensagensconfig',
            name='tpl_intro_quitacao',
            field=models.TextField(default='Segue a lista dos seus contratos com os valores de quitação:'),
        ),
        migrations.AddField(
            model_name='mensagensconfig',
            name='tpl_intro_renovacao',
            field=models.TextField(default='Segue a lista dos seus contratos com os valores de renovação:'),
        ),
        migrations.AddField(
            model_name='mensagensconfig',
            name='tpl_intro_vencimento',
            field=models.TextField(default='Segue os vencimentos dos seus contratos:'),
        ),
        migrations.AlterField(
            model_name='mensagensconfig',
            name='system_prompt',
            field=models.TextField(default=PROMPT_NOVO),
        ),
        migrations.AlterField(
            model_name='mensagensconfig',
            name='tpl_lista_header',
            field=models.TextField(default=TPL_LISTA_HEADER_NOVO, help_text='Usado só quando o cliente pede 2+ tipos de dado diferentes juntos (ex.: laudo + lista) -- cada tipo sozinho usa seu próprio intro (tpl_intro_*).'),
        ),
        migrations.RunPython(substituir_defaults_customizaveis, noop_reverse),
    ]
