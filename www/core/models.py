from django.conf import settings
from django.db import models

from .mensagens_defaults import (
    DEFAULT_MSG_BOLETO_INTRO,
    DEFAULT_MSG_CADASTRO_NAO_LOCALIZADO,
    DEFAULT_MSG_CPF_INVALIDO,
    DEFAULT_MSG_CPF_NAO_BATE,
    DEFAULT_MSG_DB_DESATUALIZADA,
    DEFAULT_MSG_DUVIDA_ANOTADA,
    DEFAULT_MSG_FALLBACK_SEM_RESPOSTA,
    DEFAULT_MSG_INFO_NEGADA_DESCONHECIDO,
    DEFAULT_MSG_INSISTIU_HUMANO,
    DEFAULT_MSG_MIDIA_NAO_SUPORTADA,
    DEFAULT_MSG_NEUTRA_PADRAO,
    DEFAULT_MSG_PEDIR_CPF,
    DEFAULT_MSG_QUITACAO_GARANTIA,
    DEFAULT_MSG_RENOVACAO_PROXIMO_VENCIMENTO,
    DEFAULT_MSG_SAUDACAO,
    DEFAULT_MSG_SEM_CONTRATOS_ATIVOS,
    DEFAULT_MSG_SEM_INFO_FAQ,
    DEFAULT_MSG_SEGUNDA_VIA_CONFIRMA,
    DEFAULT_MSG_SOLICITACAO_CRIADA,
    DEFAULT_MSG_VERIFICACAO_FALHOU,
    DEFAULT_MSG_VERIFICACAO_OK,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TPL_CONTRATO_PARCELA,
    DEFAULT_TPL_CONTRATO_QUITACAO,
    DEFAULT_TPL_CONTRATO_RENOVACAO,
    DEFAULT_TPL_CONTRATO_RESUMO,
    DEFAULT_TPL_CONTRATO_VENCIMENTO,
    DEFAULT_TPL_LISTA_FOOTER,
    DEFAULT_TPL_LISTA_HEADER,
    DEFAULT_TPL_SAUDACAO_CLIENTE,
    DEFAULT_TPL_TOTALIZADOR,
    DEFAULT_TPL_TOTALIZADOR_SEM_VALOR,
)


class Cliente(models.Model):
    """Mirrors the legacy `clientes` table (0886.sqlite3)."""

    cpf = models.CharField(max_length=14, primary_key=True)
    nome = models.CharField(max_length=255, blank=True)

    situacao_cpf = models.CharField(max_length=30, blank=True)
    situacao_cadastro = models.CharField(max_length=30, blank=True)

    logradouro = models.CharField(max_length=255, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=15, blank=True)

    aniversario = models.DateField(null=True, blank=True)
    data_da_captura_das_renovacoes = models.DateField(null=True, blank=True)

    documento = models.TextField(blank=True)
    boleto_emitido = models.BooleanField(default=False)

    bloqueado_ia = models.BooleanField(
        default=False, help_text="Se marcado, o bot nunca responde automaticamente a este cliente."
    )
    bloqueado_motivo = models.TextField(blank=True)
    bloqueado_em = models.DateTimeField(null=True, blank=True)

    conta_nsgd = models.CharField(max_length=60, blank=True)
    codigo_de_barras = models.CharField(max_length=80, blank=True)
    codigo_sipen = models.CharField(max_length=60, blank=True)
    cocli = models.CharField(max_length=60, blank=True)
    limite_especial = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    emails = models.JSONField(default=list, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def __str__(self):
        return f"{self.nome} ({self.cpf})"

    @classmethod
    def buscar_por_cpf(cls, cpf_raw):
        """Busca um cliente pelo CPF, aceitando entrada formatada (com pontos
        e traço) ou só dígitos — o parâmetro é sempre normalizado antes da
        busca.

        Com a migração 0014 (core), `Cliente.cpf` no banco já está
        normalizado (11 dígitos) na imensa maioria dos casos, então a busca
        principal é uma igualdade exata pelo valor limpo. Mantém um fallback
        pelo formato pontuado só para os raros registros que ficaram como
        estavam por colisão de normalização (ver `core.utils.normalizar_cpfs_clientes`).
        """
        if not cpf_raw:
            return None
        from core.utils import normalizar_cpf, formatar_cpf_pontuado
        clean = normalizar_cpf(cpf_raw)
        if not clean:
            return None
        cliente = cls.objects.filter(cpf=clean).first()
        if cliente is not None:
            return cliente
        return cls.objects.filter(cpf=formatar_cpf_pontuado(cpf_raw)).first()


class Telefone(models.Model):
    """Normalized phone numbers for a Cliente, used to match WhatsApp remoteJid."""

    cliente = models.ForeignKey(Cliente, related_name="telefones", on_delete=models.CASCADE)
    numero = models.CharField(max_length=20, db_index=True, help_text="E.164, ex: +5567999755980")
    numero_bruto = models.CharField(max_length=20, blank=True, help_text="Como veio do sistema legado")

    class Meta:
        verbose_name = "Telefone"
        verbose_name_plural = "Telefones"
        constraints = [
            models.UniqueConstraint(fields=["cliente", "numero"], name="unique_cliente_numero"),
        ]

    def __str__(self):
        return self.numero


class AgenciaPenhor(models.Model):
    """Mirrors the legacy `agencias_penhor` table."""

    codigo = models.CharField(max_length=20, primary_key=True)
    dv = models.CharField(max_length=5, blank=True)
    nome = models.CharField(max_length=255, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    situacao = models.CharField(max_length=60, blank=True)
    tipo = models.CharField(max_length=60, blank=True)
    porte = models.CharField(max_length=60, blank=True)
    penhor = models.CharField(max_length=60, blank=True)
    logradouro = models.CharField(max_length=255, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cep = models.CharField(max_length=15, blank=True)

    class Meta:
        verbose_name = "Agência de Penhor"
        verbose_name_plural = "Agências de Penhor"

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class Licitacao(models.Model):
    """Mirrors the legacy `licitacoes` table (low priority, ~1 row)."""

    numero = models.CharField(max_length=30, primary_key=True)
    situacao = models.CharField(max_length=60, blank=True)
    centralizadora = models.CharField(max_length=255, blank=True)
    data = models.CharField(max_length=60, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    local_retirada = models.CharField(max_length=255, blank=True)
    periodo_retirada = models.CharField(max_length=120, blank=True)
    periodo_lances = models.CharField(max_length=120, blank=True)
    periodo_exposicao = models.CharField(max_length=120, blank=True)
    participantes = models.TextField(blank=True)
    urls_arquivos = models.TextField(blank=True)
    data_limite_pagamento = models.CharField(max_length=60, blank=True)

    class Meta:
        verbose_name = "Licitação"
        verbose_name_plural = "Licitações"

    def __str__(self):
        return self.numero


class ContratoPenhor(models.Model):
    """Mirrors the legacy `contratos` table."""

    contrato = models.CharField(max_length=30, primary_key=True)
    cliente = models.ForeignKey(
        Cliente, related_name="contratos_penhor", on_delete=models.SET_NULL, null=True, blank=True
    )
    nome = models.CharField(max_length=255, blank=True)

    data_emissao = models.DateField(null=True, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)
    data_situacao = models.DateField(null=True, blank=True)
    data_tva = models.DateField(null=True, blank=True)
    data_entrega_garantia = models.DateField(null=True, blank=True)
    data_dos_dados = models.DateField(null=True, blank=True)
    data_do_laudo = models.DateField(null=True, blank=True)

    prazo = models.CharField(max_length=30, blank=True)
    atraso = models.IntegerField(null=True, blank=True, help_text="Dias de atraso")

    # Free-text status coming from the legacy system: kept as plain text
    # (not a hard enum) because new codes/labels can appear over time in the
    # source ERP and we don't want import to fail on unseen values. Observed
    # values (situacao / situacao_codigo) at model-design time:
    #   Contrato Avaliado - Pré-contrato Cancelado   (AVCL)
    #   Contrato Liquidado                            (LQ)
    #   Contrato Liquidado Vendido em Licitação        (LQVL)
    #   Contrato Liquidado Com Dispensa de Encargos    (LQDE)
    #   Contrato Renovado Relacionado para Licitação   (RR)
    #   Contrato Renovado                              (RN)
    #   Objeto Abandonado Avaliado - Pré-abandono      (OBJA)
    #   Contrato Avaliado - Pré-contrato               (AVAL)
    #   Contrato em Sub Judice, Liquidado              (SJLQ)
    #   PAGAMENTO/RECEBIMENTO - SALDO DE LICITAÇÃO     (LQSD)
    #   Empréstimo Novo Relacionado para Licitação     (EMRL)
    #   Empréstimo Novo                                (EMNV)
    situacao = models.CharField(max_length=100, blank=True, db_index=True)
    situacao_codigo = models.CharField(max_length=10, blank=True, db_index=True)

    modalidade = models.CharField(max_length=10, blank=True)
    acerto_de_valores = models.CharField(max_length=60, blank=True)
    avaliador = models.CharField(max_length=120, blank=True)
    matricula_avaliador = models.CharField(max_length=60, blank=True)
    depesas_vinculadas = models.CharField(max_length=120, blank=True)
    faixa = models.CharField(max_length=60, blank=True)
    liquidacao = models.CharField(max_length=60, blank=True)

    qt_parcelas = models.IntegerField(null=True, blank=True)
    qt_parcelas_pagas = models.IntegerField(null=True, blank=True)
    qt_renovacoes = models.IntegerField(null=True, blank=True)

    # Whether this contract was flagged in the legacy `contratos_parcelados`
    # list for its client (installment plan), computed at import time.
    parcelado = models.BooleanField(default=False)

    vlr_avaliacao = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_emprestimo = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_atualizacao_monetaria = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_desconto = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_iof = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_juros = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_liquido = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_maximo_emprestimo = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_mora = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_multa = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_rem_atraso = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_renovacao_30 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_renovacao_60 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_renovacao_90 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_renovacao_120 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_renovacao_150 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_renovacao_180 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_tar = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_troco = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_parcela = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    vlr_parcela_atualizada = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    tarifa_custodia = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    fator_de_atualizacao_avaliacao = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )
    margem = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    peso = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Gramas")
    valor_p_grama = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    laudo = models.TextField(blank=True, help_text="Descrição da garantia/joia")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato de Penhor"
        verbose_name_plural = "Contratos de Penhor"

    def __str__(self):
        return self.contrato


# --- WhatsApp conversation flow --------------------------------------------


class Conversa(models.Model):
    class Estado(models.TextChoices):
        NOVA = "nova", "Nova"
        AGUARDANDO_VERIFICACAO = "aguardando_verificacao", "Aguardando verificação"
        VERIFICADA = "verificada", "Verificada"
        INTENCAO_CAPTURADA = "intencao_capturada", "Intenção capturada"
        AGUARDANDO_BOLETO = "aguardando_boleto", "Aguardando boleto"
        BOLETO_ENVIADO = "boleto_enviado", "Boleto enviado"
        ENCERRADA = "encerrada", "Encerrada"

    class TipoContato(models.TextChoices):
        CLIENTE = "cliente", "Cliente (PHN_)"
        PESSOAL = "pessoal", "Contato pessoal"
        DESCONHECIDO = "desconhecido", "Não salvo"

    class MetodoIdentificacao(models.TextChoices):
        NENHUM = "nenhum", "Não identificado"
        TELEFONE = "telefone", "Telefone cadastrado"
        CPF = "cpf", "CPF digitado"

    cliente = models.ForeignKey(
        Cliente, related_name="conversas", on_delete=models.SET_NULL, null=True, blank=True
    )
    remote_jid = models.CharField(max_length=40, db_index=True, help_text="Número bruto do WhatsApp")
    estado = models.CharField(max_length=30, choices=Estado.choices, default=Estado.NOVA)
    tipo_contato = models.CharField(max_length=15, choices=TipoContato.choices, default=TipoContato.DESCONHECIDO)
    nome_salvo = models.CharField(max_length=255, blank=True, help_text="Nome salvo na agenda do dono (PHN_CPF_NOME) quando disponível")
    identificacao = models.CharField(
        max_length=10,
        choices=MetodoIdentificacao.choices,
        default=MetodoIdentificacao.NENHUM,
        help_text="Como o contato foi identificado nesta conversa: telefone cadastrado (não expira) ou CPF digitado (expira em 24h).",
    )
    cpf_verificado = models.CharField(max_length=14, blank=True, default="", help_text="CPF confirmado pelo cliente nesta conversa")
    slots = models.JSONField(default=dict, blank=True, help_text="Estado de slot-filling entre turnos (ex.: cpfs pendentes, contratos a confirmar)")
    precisa_revisao_humana = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    processando_desde = models.DateTimeField(
        null=True, blank=True,
        help_text="Mutex leve: carimbado quando process_mensagem começa a processar esta conversa, limpo ao final.",
    )
    ultima_interacao = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Conversa"
        verbose_name_plural = "Conversas"

    def __str__(self):
        return f"Conversa {self.remote_jid} ({self.estado})"


class Mensagem(models.Model):
    class Direcao(models.TextChoices):
        IN = "in", "Recebida"
        OUT = "out", "Enviada"

    class TipoMidia(models.TextChoices):
        IMAGE = "image", "Imagem"
        AUDIO = "audio", "Áudio"
        VIDEO = "video", "Vídeo"
        DOCUMENT = "document", "Documento"

    conversa = models.ForeignKey(Conversa, related_name="mensagens", on_delete=models.CASCADE)
    direcao = models.CharField(max_length=3, choices=Direcao.choices)
    texto = models.TextField(blank=True)
    wa_message_id = models.CharField(max_length=120, unique=True, null=True, blank=True)
    push_name = models.CharField(max_length=255, blank=True, help_text="Nome de perfil/salvo informado pelo webhook")
    tipo_midia = models.CharField(
        max_length=10, choices=TipoMidia.choices, blank=True, default="",
        help_text="Vazio = sem mídia. Preenchido a partir do payload da Evolution (IN) ou pelo operador (OUT).",
    )
    arquivo = models.FileField(
        upload_to="conversa_arquivos/%Y/%m/", blank=True, null=True,
        help_text="Anexo enviado pelo operador (mensagens OUT).",
    )
    enviado_ok = models.BooleanField(
        null=True, blank=True,
        help_text="OUT: resultado do envio via Evolution. None = mensagem IN ou registro legado.",
    )
    payload_bruto = models.JSONField(default=dict, blank=True)
    respondida_em = models.DateTimeField(
        null=True, blank=True,
        help_text="Quando o bot considerou esta mensagem IN respondida (controle do lote do debounce).",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mensagem"
        verbose_name_plural = "Mensagens"
        ordering = ["criado_em"]

    def __str__(self):
        return f"[{self.direcao}] {self.texto[:40]}"


class ContatoSalvo(models.Model):
    """Cache da agenda de contatos do WhatsApp do dono, populada pela
    sincronização com a Evolution API. Permite diferenciar cliente
    (PHN_CPF_NOME) de contato pessoal (ignorar) e de não-salvo (saudar)."""

    class Tipo(models.TextChoices):
        CLIENTE = "cliente", "Cliente (PHN_)"
        PESSOAL = "pessoal", "Contato pessoal"

    remote_jid = models.CharField(max_length=40, unique=True, help_text="Jid bruto do WhatsApp (ex: 5567999755980@s.whatsapp.net)")
    nome_salvo = models.CharField(max_length=255, blank=True, help_text="Nome como salvo na agenda do dono")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.PESSOAL)
    cpf = models.CharField(max_length=14, blank=True, help_text="CPF extraído do nome PHN_<cpf>_<nome>, quando aplicável")
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contato salvo"
        verbose_name_plural = "Contatos salvos"

    def __str__(self):
        return f"{self.nome_salvo or self.remote_jid} ({self.tipo})"


class BotConfig(models.Model):
    """Singleton switch to pause/resume automatic AI processing and replies,
    plus operational knobs (data freshness, closing time, unknown-contact
    greeting)."""

    ativo = models.BooleanField(default=False)
    ultima_atualizacao_dados = models.DateTimeField(
        null=True, blank=True,
        help_text="Carimbado pelo comando import_sqlite. Base para o freshness check.",
    )
    freshness_horas = models.PositiveIntegerField(
        default=24,
        help_text="Idade máxima (em horas) do último import para considerar a database atualizada.",
    )
    debounce_segundos = models.PositiveIntegerField(
        default=120,
        help_text="Segundos de silêncio do cliente antes de a IA responder. 0 = responder imediatamente. Respostas sem IA (CPF, saudação, mídia) continuam imediatas.",
    )
    horario_encerramento = models.TimeField(
        null=True, blank=True,
        help_text="Horário (America/Sao_Paulo) em que o bot desativa sozinho. Vazio = não desativa.",
    )
    responder_desconhecidos = models.BooleanField(
        default=True,
        help_text="Se True, saúda contatos não salvos. Desligue se prefere só atender clientes já cadastrados.",
    )
    dias_resgate_garantia = models.PositiveIntegerField(
        default=1,
        help_text="Dias após a quitação a partir de quando o cliente pode resgatar as garantias.",
    )
    ultimo_encerramento_auto = models.DateField(
        null=True, blank=True,
        help_text="Data do último encerramento automático; evita desligar mais de uma vez por dia.",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração do bot"
        verbose_name_plural = "Configuração do bot"

    def __str__(self):
        return "Bot ativo" if self.ativo else "Bot desativado"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def database_atualizada(self, agora=None) -> bool:
        """True se o último import_sqlite está dentro de freshness_horas."""
        if not self.ultima_atualizacao_dados:
            return False
        from django.utils import timezone
        ref = agora or timezone.now()
        return (ref - self.ultima_atualizacao_dados).total_seconds() <= self.freshness_horas * 3600


class MensagensConfig(models.Model):
    """Singleton com o prompt da IA e as mensagens fixas, editáveis no painel
    (tela "Mensagens & Prompt"). Os defaults vivem em core/mensagens_defaults.py,
    fonte única também usada pelo fallback de ia/services.py."""

    system_prompt = models.TextField(default=DEFAULT_SYSTEM_PROMPT)
    msg_saudacao = models.TextField(default=DEFAULT_MSG_SAUDACAO)
    msg_cadastro_nao_localizado = models.TextField(default=DEFAULT_MSG_CADASTRO_NAO_LOCALIZADO)
    msg_pedir_cpf = models.TextField(default=DEFAULT_MSG_PEDIR_CPF)
    msg_cpf_invalido = models.TextField(default=DEFAULT_MSG_CPF_INVALIDO)
    msg_cpf_nao_bate = models.TextField(default=DEFAULT_MSG_CPF_NAO_BATE)
    msg_verificacao_ok = models.TextField(default=DEFAULT_MSG_VERIFICACAO_OK)
    msg_verificacao_falhou = models.TextField(default=DEFAULT_MSG_VERIFICACAO_FALHOU)
    msg_sem_info_faq = models.TextField(default=DEFAULT_MSG_SEM_INFO_FAQ)
    msg_db_desatualizada = models.TextField(default=DEFAULT_MSG_DB_DESATUALIZADA)
    msg_sem_contratos_ativos = models.TextField(default=DEFAULT_MSG_SEM_CONTRATOS_ATIVOS)
    msg_solicitacao_criada = models.TextField(default=DEFAULT_MSG_SOLICITACAO_CRIADA)
    msg_boleto_intro = models.TextField(default=DEFAULT_MSG_BOLETO_INTRO)
    msg_renovacao_proximo_vencimento = models.TextField(default=DEFAULT_MSG_RENOVACAO_PROXIMO_VENCIMENTO)
    msg_quitacao_garantia = models.TextField(default=DEFAULT_MSG_QUITACAO_GARANTIA)
    msg_segunda_via_confirma = models.TextField(default=DEFAULT_MSG_SEGUNDA_VIA_CONFIRMA)
    msg_insistiu_humano = models.TextField(default=DEFAULT_MSG_INSISTIU_HUMANO)
    msg_neutra_padrao = models.TextField(default=DEFAULT_MSG_NEUTRA_PADRAO)
    tpl_saudacao_cliente = models.TextField(default=DEFAULT_TPL_SAUDACAO_CLIENTE)
    tpl_contrato_vencimento = models.TextField(default=DEFAULT_TPL_CONTRATO_VENCIMENTO)
    tpl_contrato_renovacao = models.TextField(default=DEFAULT_TPL_CONTRATO_RENOVACAO)
    tpl_contrato_quitacao = models.TextField(default=DEFAULT_TPL_CONTRATO_QUITACAO)
    tpl_contrato_parcela = models.TextField(default=DEFAULT_TPL_CONTRATO_PARCELA)
    tpl_contrato_resumo = models.TextField(default=DEFAULT_TPL_CONTRATO_RESUMO)
    tpl_lista_header = models.TextField(default=DEFAULT_TPL_LISTA_HEADER)
    tpl_lista_footer = models.TextField(
        default=DEFAULT_TPL_LISTA_FOOTER,
        help_text="(não usado — fechamento incorporado ao totalizador)",
    )
    tpl_totalizador = models.TextField(default=DEFAULT_TPL_TOTALIZADOR)
    tpl_totalizador_sem_valor = models.TextField(default=DEFAULT_TPL_TOTALIZADOR_SEM_VALOR)
    msg_fallback_sem_resposta = models.TextField(default=DEFAULT_MSG_FALLBACK_SEM_RESPOSTA)
    msg_duvida_anotada = models.TextField(
        default=DEFAULT_MSG_DUVIDA_ANOTADA,
        help_text="Anexada ao final da fila quando há dúvidas sem FAQ junto com outras ações. Use {duvidas}.",
    )
    msg_info_negada_desconhecido = models.TextField(default=DEFAULT_MSG_INFO_NEGADA_DESCONHECIDO)
    msg_midia_nao_suportada = models.TextField(default=DEFAULT_MSG_MIDIA_NAO_SUPORTADA)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mensagens & Prompt"
        verbose_name_plural = "Mensagens & Prompt"

    def __str__(self):
        return "Mensagens & Prompt"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class FAQ(models.Model):
    pergunta = models.CharField(max_length=255)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"

    def __str__(self):
        return self.pergunta


class FAQResposta(models.Model):
    faq = models.ForeignKey(FAQ, related_name="respostas", on_delete=models.CASCADE)
    ordem = models.PositiveIntegerField(default=0, help_text="Ordem de envio das mensagens de resposta")
    texto = models.TextField(blank=True, help_text="Mensagem de texto da resposta")
    arquivo = models.FileField(upload_to="faq_arquivos/", blank=True, null=True, help_text="Arquivo opcional")

    class Meta:
        ordering = ["ordem", "id"]
        verbose_name = "Mensagem de Resposta"
        verbose_name_plural = "Mensagens de Resposta"

    def __str__(self):
        if self.arquivo:
            return f"[{self.ordem}] Arquivo: {self.arquivo.name} - {self.texto[:30]}"
        return f"[{self.ordem}] {self.texto[:50]}"


class FAQSugerida(models.Model):
    """Pergunta que a IA não conseguiu responder pela FAQ existente (fallback
    determinístico do bot). Fica pendente de revisão humana; se aprovada,
    vira uma FAQ real. Perguntas repetidas (mesmo texto, ainda pendente) só
    incrementam `ocorrencias` em vez de duplicar a linha."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADA = "aprovada", "Aprovada"
        REJEITADA = "rejeitada", "Rejeitada"

    pergunta = models.CharField(max_length=255, help_text="Pergunta resumida sugerida pela IA")
    pergunta_original = models.TextField(blank=True, help_text="Mensagem literal do cliente")
    conversa = models.ForeignKey(
        Conversa, related_name="faqs_sugeridas", on_delete=models.SET_NULL, null=True, blank=True
    )
    ocorrencias = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)
    faq_criada = models.ForeignKey(FAQ, on_delete=models.SET_NULL, null=True, blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    revisado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ocorrencias", "-criado_em"]
        verbose_name = "FAQ sugerida"
        verbose_name_plural = "FAQs sugeridas"

    def __str__(self):
        return f"{self.pergunta} ({self.get_status_display()}, x{self.ocorrencias})"

    @classmethod
    def registrar(cls, pergunta, conversa=None, pergunta_original=""):
        """Cria uma FAQSugerida ou, se já existir uma PENDENTE com a mesma
        pergunta (case-insensitive), incrementa `ocorrencias` e retorna essa."""
        pergunta = (pergunta or "").strip()
        existente = cls.objects.filter(status=cls.Status.PENDENTE, pergunta__iexact=pergunta).first()
        if existente:
            existente.ocorrencias = models.F("ocorrencias") + 1
            existente.save(update_fields=["ocorrencias"])
            existente.refresh_from_db(fields=["ocorrencias"])
            return existente
        return cls.objects.create(
            pergunta=pergunta,
            pergunta_original=pergunta_original,
            conversa=conversa,
        )


class Solicitacao(models.Model):
    class Tipo(models.TextChoices):
        QUITAR = "quitar", "Quitar"
        AMORTIZAR = "amortizar", "Amortizar"
        RENOVAR = "renovar", "Renovar"
        PARCELA = "parcela", "Parcela"
        SEGUNDA_VIA = "segunda_via", "Segunda via de boleto"
        DUVIDA = "duvida", "Dúvida"

    class Escopo(models.TextChoices):
        TODOS = "todos", "Todos os contratos"
        ESPECIFICOS = "especificos", "Contratos específicos"
        NAO_APLICAVEL = "nao_aplicavel", "Não aplicável"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        BOLETO_ENVIADO = "boleto_enviado", "Boleto enviado"
        CONCLUIDA = "concluida", "Concluída"

    cliente = models.ForeignKey(
        Cliente, related_name="solicitacoes", on_delete=models.SET_NULL, null=True, blank=True
    )
    conversa = models.ForeignKey(
        Conversa, related_name="solicitacoes", on_delete=models.SET_NULL, null=True, blank=True
    )
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    escopo = models.CharField(max_length=15, choices=Escopo.choices, default=Escopo.NAO_APLICAVEL)
    contratos = models.ManyToManyField(ContratoPenhor, related_name="solicitacoes", blank=True)
    prazo_dias = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Prazo da renovação (30/60/90/120/150/180). Nulo para quitar/parcela/segunda via.",
    )
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDENTE)
    resposta_ia = models.TextField(blank=True)
    precisa_humano = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Solicitação"
        verbose_name_plural = "Solicitações"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Solicitação #{self.pk} - {self.get_tipo_display()} ({self.status})"


class Boleto(models.Model):
    solicitacao = models.ForeignKey(Solicitacao, related_name="boletos", on_delete=models.CASCADE)
    arquivo = models.FileField(upload_to="boletos/")
    linha_digitavel = models.CharField(max_length=80, blank=True, default="")
    enviado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Boleto"
        verbose_name_plural = "Boletos"

    def __str__(self):
        return f"Boleto de {self.solicitacao} ({self.arquivo.name})"


class ImportDataJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pendente", "Pendente"
        RUNNING = "andamento", "Em andamento"
        SUCCESS = "concluido", "Concluído"
        FAILED = "falhou", "Falhou"

    arquivo = models.FileField(upload_to="import_sqlite/", verbose_name="Arquivo SQLite")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Status"
    )
    counts = models.JSONField(default=dict, blank=True, verbose_name="Contagens")
    erro = models.TextField(blank=True, default="", verbose_name="Erro")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    finalizado_em = models.DateTimeField(null=True, blank=True, verbose_name="Finalizado em")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Usuário",
    )

    class Meta:
        verbose_name = "Importação de dados"
        verbose_name_plural = "Importações de dados"
        ordering = ["-criado_em"]

    def __str__(self):
        name = self.arquivo.name.split("/")[-1] if self.arquivo.name else "(sem arquivo)"
        return f"{name} — {self.get_status_display()} — {self.criado_em:%d/%m/%Y %H:%M}"
