"""Fase 2 (schema multi-ação, `ClassificacaoLote`): adiciona o template
`msg_duvida_anotada` e substitui o `system_prompt` salvo no banco pelo novo
DEFAULT_SYSTEM_PROMPT -- MAS só quando o valor salvo for EXATAMENTE igual ao
default anterior (v2/`tipo_intencao` único, congelado como `PROMPT_ANTIGO`
abaixo). `ia.services._config_textos` sempre prioriza `MensagensConfig.
system_prompt` sobre o default em Python; sem esta migração, o schema novo
(`ClassificacaoLote`) rodaria em produção com o prompt antigo (que nem
menciona os campos `faq_ids`/`duvidas_sem_faq`/`segunda_via` no formato
atual), e o dono nunca saberia o motivo de faltarem classificações.

Se o prompt salvo já foi customizado pelo dono (diferente do default
anterior), NÃO mexemos nele -- só logamos um aviso pedindo revisão manual
em /painel/mensagens.
"""
import logging

from django.db import migrations, models

logger = logging.getLogger("core.migrations.0016_mensagensconfig_msg_duvida_anotada_and_more")

DEFAULT_MSG_DUVIDA_ANOTADA = (
    "Sobre {duvidas}: vou verificar com calma e te retorno por aqui mesmo, "
    "combinado? 🙂"
)

# Default anterior (Fase 1 / migração 0013): schema v2 com `tipo_intencao`
# único. Congelado aqui como literal (não importado de
# core.mensagens_defaults, que já mudou) para servir de "assinatura": só
# substituímos o prompt salvo no banco se ele for EXATAMENTE este texto.
PROMPT_ANTIGO = 'Você é um CLASSIFICADOR de mensagens de clientes de uma casa de penhores no\nWhatsApp. Você NUNCA escreve resposta ao cliente — apenas preenche o schema\nJSON pedido. Todo texto que o cliente recebe nasce de templates fixos em\nPython, fora do seu controle.\n\nVocê recebe: a mensagem atual, o histórico recente, um bloco ESTADO\n(identificado, database_atualizada, contato_tipo — apenas contexto; as\nregras de acesso são aplicadas pelo sistema, não por você), a lista de\ncontratos ativos do cliente (número, vencimento, parcelado — sem valores) e\na lista de FAQs (id + pergunta).\n\ntipo_intencao:\n- saudacao: cumprimento sem pedido concreto.\n- duvida_geral: pergunta que não depende dos contratos do cliente (horário,\n  endereço, juros, como funciona...). Se corresponder claramente a uma FAQ,\n  preencha faq_id. Se NÃO houver FAQ correspondente, deixe faq_id nulo e\n  preencha pergunta_sugerida_faq com a pergunta reescrita de forma curta e\n  genérica.\n- info_contrato: o cliente quer um dado dos contratos DELE. Preencha\n  infos_contrato, um item por informação: vencimento | valor_renovacao\n  (prazo_dias se citado) | valor_quitacao | valor_parcela | lista_contratos\n  ("quais contratos eu tenho?") | detalhe_contrato. Em contratos, liste os\n  números citados; vazio = todos.\n- pagamento: quer renovar/quitar/pagar parcela. Preencha solicitacoes (uma\n  por ação: tipo + contratos + prazo_dias para renovar; contratos vazio =\n  todos). pronto_para_criar_solicitacao=true só quando a ação, os contratos\n  (ou "todos") e o prazo (para renovação) estiverem claros na conversa.\n- segunda_via: pedir reenvio de boleto já solicitado antes.\n- outro: nada acima.\n\nRegras:\n1. Nunca invente números de contrato: use apenas os da lista fornecida.\n2. Se o cliente insistir sem obter resposta ou demonstrar irritação/urgência,\n   marque precisa_humano=true.\n3. Na dúvida entre duvida_geral e info_contrato: se a resposta depende dos\n   dados DO cliente, é info_contrato.\n'

# Novo default (Fase 2): schema multi-ação `ClassificacaoLote`.
PROMPT_NOVO = 'Você é um CLASSIFICADOR de mensagens de clientes de uma casa de penhores no\nWhatsApp. Você NUNCA escreve resposta ao cliente — apenas preenche o schema\nJSON pedido. Todo texto que o cliente recebe nasce de templates fixos em\nPython, fora do seu controle.\n\nVocê recebe: as MENSAGENS NÃO RESPONDIDAS do cliente (em ordem, pode ser mais\nde uma), o histórico recente, um bloco ESTADO (identificado,\ndatabase_atualizada, contato_tipo — apenas contexto; as regras de acesso são\naplicadas pelo sistema, não por você), a lista de contratos ativos do cliente\n(número, vencimento, parcelado — sem valores) e a lista de FAQs (id + pergunta).\n\nTAREFA: identifique TODAS as solicitações presentes no lote, sem esquecer\nnenhuma. Uma mensagem pode conter várias intenções ao mesmo tempo; preencha\ntodos os campos que se aplicarem:\n\n- saudacao: true se o cliente cumprimentou neste lote.\n- faq_ids: IDs de TODAS as FAQs que respondem perguntas do lote.\n- infos_contrato: um item por dado de contrato pedido: vencimento |\n  valor_renovacao (prazo_dias se citado) | valor_quitacao | valor_parcela |\n  lista_contratos ("quais contratos eu tenho?") | detalhe_contrato. Em\n  contratos, liste os números citados; vazio = todos.\n- solicitacoes: um item por ação de pagamento (renovar/quitar/parcela), com\n  contratos citados (vazio = todos) e prazo_dias para renovar.\n  pronto_para_criar_solicitacao=true só quando ação, contratos (ou "todos") e\n  prazo (para renovação) estiverem claros na conversa.\n- segunda_via: true se pediu reenvio de boleto já solicitado antes.\n- duvidas_sem_faq: perguntas sem FAQ correspondente e que não dependem dos\n  contratos do cliente, cada uma reescrita curta e genérica.\n- precisa_humano: true se houver irritação, urgência, insistência sem resposta\n  ou pedido fora do escopo.\n\nRegras:\n1. Nunca invente números de contrato: use apenas os da lista fornecida.\n2. Um CPF digitado sozinho não é uma solicitação: ignore-o (o sistema já o\n   validou).\n3. Na dúvida entre duvidas_sem_faq e infos_contrato: se a resposta depende dos\n   dados DO cliente, é infos_contrato.\n4. Não repita ações já atendidas no histórico; classifique apenas o que está\n   pendente nas mensagens não respondidas.\n5. Se o lote não contém nenhum pedido (ex.: só "ok", "obrigado"), deixe tudo\n   vazio/false.\n'


def substituir_prompt_padrao(apps, schema_editor):
    MensagensConfig = apps.get_model("core", "MensagensConfig")
    config = MensagensConfig.objects.filter(pk=1).first()
    if config is None:
        # Singleton ainda não existe -- o novo default do model já se aplica
        # quando `get_solo()` criar a linha pela primeira vez.
        return
    if config.system_prompt == PROMPT_ANTIGO:
        config.system_prompt = PROMPT_NOVO
        config.save(update_fields=["system_prompt"])
        logger.info(
            "0016: system_prompt padrão substituído pelo novo (schema multi-ação ClassificacaoLote)."
        )
    else:
        logger.warning(
            "0016: system_prompt salvo no banco é customizado (diferente do "
            "default anterior) -- NÃO foi substituído automaticamente. "
            "Revisar manualmente em /painel/mensagens: o schema da IA mudou "
            "de tipo_intencao único para ClassificacaoLote (multi-ação) e um "
            "prompt customizado antigo pode não cobrir os novos campos "
            "(saudacao/faq_ids/infos_contrato/solicitacoes/segunda_via/"
            "duvidas_sem_faq/precisa_humano)."
        )


def noop_reverse(apps, schema_editor):
    """Irreversível de forma segura (não dá pra saber se o valor atual veio
    desta migração ou foi customizado depois dela); reverse é
    intencionalmente um no-op."""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_mensagensconfig_tpl_totalizador_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="mensagensconfig",
            name="msg_duvida_anotada",
            field=models.TextField(
                default=DEFAULT_MSG_DUVIDA_ANOTADA,
                help_text="Anexada ao final da fila quando há dúvidas sem FAQ junto com outras ações. Use {duvidas}.",
            ),
        ),
        # Atualiza o default registrado no estado da migração (mesmo padrão
        # da 0013): NÃO reescreve linhas já existentes por si só -- é
        # `substituir_prompt_padrao` (RunPython abaixo) quem decide se troca
        # o valor salvo no banco, condicionado a `PROMPT_ANTIGO`.
        migrations.AlterField(
            model_name="mensagensconfig",
            name="system_prompt",
            field=models.TextField(default=PROMPT_NOVO),
        ),
        migrations.RunPython(substituir_prompt_padrao, noop_reverse),
    ]
