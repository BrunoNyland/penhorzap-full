"""Testes do motor novo do bot (WS-D2).

Escopo: `whatsapp/tasks.py` (`process_mensagem` e o lock/coalescência),
`whatsapp/respostas_contrato.py` (renderer determinístico) e
`whatsapp/views.py` (`_extrair_conteudo` + webhook). `whatsapp.tasks.get_client`
e `whatsapp.tasks.extrair_intencao` são sempre mockados aqui -- nenhum teste
bate na Evolution API real nem no Gemini.
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    BotConfig,
    Cliente,
    Conversa,
    ContratoPenhor,
    FAQ,
    FAQResposta,
    FAQSugerida,
    Mensagem,
    MensagensConfig,
    Solicitacao,
    Telefone,
)
from ia.schemas import (
    CampoValor,
    ClassificacaoLote,
    InfoContrato,
    InfoContratoPedido,
    SolicitacaoDraft,
    TipoPagamento,
)
from whatsapp.respostas_contrato import (
    _limpar_peso_do_laudo,
    _montar_totalizador_geral,
    formatar_data,
    formatar_moeda,
    formatar_peso,
    render_template,
    renderizar_infos_contrato,
)
from whatsapp.tasks import (
    MAX_MENSAGENS_TURNO,
    PAUSA_FANOUT,
    _contratos_ativos_values,
    _enviar_fila,
    _mensagens_pendentes,
    process_lote_conversa,
    process_mensagem,
)
from whatsapp.views import _extrair_conteudo

from django_q.models import Schedule


def _classificacao(**kwargs):
    """Constrói um `ClassificacaoLote` de teste: todos os campos partem do
    "neutro" (nenhuma ação) e os testes só sobrescrevem o que precisam via
    kwargs (ex.: `_classificacao(saudacao=True)`,
    `_classificacao(infos_contrato=[...])`, `_classificacao(faq_ids=[1, 2])`)."""
    defaults = dict(
        saudacao=False,
        faq_ids=[],
        infos_contrato=[],
        solicitacoes=[],
        pronto_para_criar_solicitacao=False,
        segunda_via=False,
        duvidas_sem_faq=[],
        precisa_humano=False,
    )
    defaults.update(kwargs)
    return ClassificacaoLote(**defaults)


class WhatsappTasksTestCase(TestCase):
    """Base comum: bot ativo, database fresca, client Evolution mockado."""

    def setUp(self):
        self.bot = BotConfig.get_solo()
        self.bot.ativo = True
        self.bot.ultima_atualizacao_dados = timezone.now()
        self.bot.freshness_horas = 24
        # Fase 3 (debounce): kill-switch ligado por padrão nos testes
        # existentes -- mantém o processamento síncrono (1 mensagem = 1
        # chamada de IA imediata) sem precisar reescrever toda a suíte.
        # `DebounceTests` sobrescreve para testar o comportamento com
        # debounce > 0.
        self.bot.debounce_segundos = 0
        self.bot.save()

        self.msgs = MensagensConfig.get_solo()

        self.mock_client = MagicMock()
        self.mock_client.send_text.return_value = True
        self.mock_client.send_file.return_value = True
        self.mock_client.mark_as_read.return_value = True

        patcher = patch("whatsapp.tasks.get_client", return_value=self.mock_client)
        self.mock_get_client = patcher.start()
        self.addCleanup(patcher.stop)

        # `_enviar_fila` pausa PAUSA_FANOUT segundos entre mensagens do
        # fan-out -- mockado aqui pra não deixar a suíte lenta (o pacing em
        # si tem cobertura própria em EnviarFilaTests).
        sleep_patcher = patch("whatsapp.tasks.time.sleep")
        self.mock_sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def _in(self, conv, texto, push_name=""):
        return Mensagem.objects.create(
            conversa=conv, direcao=Mensagem.Direcao.IN, texto=texto, push_name=push_name,
        )

    def _last_out_texto(self, conv):
        msg = conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("-criado_em").first()
        return msg.texto if msg else None


class IdentificacaoTelefoneTests(WhatsappTasksTestCase):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(cpf="52998224725", nome="Joana Souza")
        Telefone.objects.create(cliente=self.cliente, numero="+5567999755980")
        self.conv = Conversa.objects.create(remote_jid="5567999755980@s.whatsapp.net")

    @patch("whatsapp.tasks.extrair_intencao")
    def test_primeira_interacao_saudacao_nominal_sem_cpf(self, mock_ia):
        mensagem = self._in(self.conv, "Oi")
        process_mensagem(mensagem.id)

        mock_ia.assert_not_called()  # primeira interação encerra o turno antes da IA
        self.mock_client.send_text.assert_called_once()
        texto_enviado = self._last_out_texto(self.conv)
        self.assertIn("Joana", texto_enviado)
        self.assertNotIn("CPF", texto_enviado)

        self.conv.refresh_from_db()
        self.assertEqual(self.conv.identificacao, Conversa.MetodoIdentificacao.TELEFONE)

    @patch("whatsapp.tasks.extrair_intencao")
    def test_identificacao_por_telefone_nunca_expira(self, mock_ia):
        # Conversa já identificada por telefone há muito tempo (verified_at
        # antigo/ausente -- o campo nem é usado no caminho telefone) e já com
        # OUT anterior (não é mais a primeira interação).
        self.conv.identificacao = Conversa.MetodoIdentificacao.TELEFONE
        self.conv.tipo_contato = Conversa.TipoContato.CLIENTE
        self.conv.cliente = self.cliente
        self.conv.verified_at = timezone.now() - timedelta(hours=999)
        self.conv.save()
        Mensagem.objects.create(conversa=self.conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        mock_ia.return_value = _classificacao(
            infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
        )
        mensagem = self._in(self.conv, "quando vence meu contrato?")
        process_mensagem(mensagem.id)

        self.conv.refresh_from_db()
        self.assertEqual(self.conv.identificacao, Conversa.MetodoIdentificacao.TELEFONE)
        texto = self._last_out_texto(self.conv)
        self.assertNotEqual(texto, self.msgs.msg_pedir_cpf)
        self.assertNotIn("CPF", texto)


class DesconhecidoTests(WhatsappTasksTestCase):
    def test_desconhecido_pedindo_info_contrato_recebe_cadastro_nao_localizado(self):
        conv = Conversa.objects.create(remote_jid="5567900000001@s.whatsapp.net")
        # Precisa já ter um OUT anterior para não cair no "saúda desconhecido"
        # do primeiro turno (passo 4 do fluxo) antes de chegar na IA.
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(conv, "quanto devo no meu contrato?")
            process_mensagem(mensagem.id)

        conv.refresh_from_db()
        self.assertEqual(conv.tipo_contato, Conversa.TipoContato.DESCONHECIDO)
        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_cadastro_nao_localizado)

    def test_contato_tipo_cliente_sem_registro_pede_cpf(self):
        # PHN_<cpf>_<nome> na agenda mas o CPF não existe no cadastro de
        # clientes -> tipo_contato=CLIENTE, cliente=None -> pede CPF (branch
        # "else" do gate, distinto do desconhecido puro).
        conv = Conversa.objects.create(remote_jid="5567900000002@s.whatsapp.net")
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(conv, "quando vence?", push_name="PHN_99999999999_Fulano")
            process_mensagem(mensagem.id)

        conv.refresh_from_db()
        self.assertEqual(conv.tipo_contato, Conversa.TipoContato.CLIENTE)
        self.assertIsNone(conv.cliente)
        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_pedir_cpf)
        self.assertEqual(conv.estado, Conversa.Estado.AGUARDANDO_VERIFICACAO)

    def test_desconhecido_verificado_por_cpf_pedindo_info_recebe_negacao(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        conv = Conversa.objects.create(
            remote_jid="5567900000003@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.DESCONHECIDO,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.CPF,
            cpf_verificado="52998224725",
            verified_at=timezone.now(),
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(conv, "quando vence meu contrato?")
            process_mensagem(mensagem.id)

        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_info_negada_desconhecido)

    def test_desconhecido_verificado_por_cpf_pagamento_e_permitido(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.DESCONHECIDO,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.CPF,
            cpf_verificado="52998224725",
            verified_at=timezone.now(),
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.QUITAR, contratos=["C1"])],
                pronto_para_criar_solicitacao=True,
            )
            mensagem = self._in(conv, "quero quitar o contrato C1")
            process_mensagem(mensagem.id)

        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_solicitacao_criada)
        self.assertNotEqual(self._last_out_texto(conv), self.msgs.msg_info_negada_desconhecido)

    def test_pagamento_indefinido_pergunta_renovacao_ou_quitacao(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            vlr_emprestimo=100.0,
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.INDEFINIDO, contratos=[])],
                pronto_para_criar_solicitacao=True,
            )
            mensagem = self._in(conv, "preciso do boleto do penhor")
            process_mensagem(mensagem.id)

        resposta = self._last_out_texto(conv)
        self.assertIn("O boleto seria de renovação? ou quitação?", resposta)
        self.assertIn("C1", resposta)
        self.assertFalse(Solicitacao.objects.filter(conversa=conv).exists())

    def test_pagamento_incompleto_nao_repete_contratos_se_ja_enviado_recentemente(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            vlr_emprestimo=100.0,
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
        )
        # Simula que o contrato já foi enviado nos últimos 10 minutos
        Mensagem.objects.create(
            conversa=conv, 
            direcao=Mensagem.Direcao.OUT, 
            texto="📄 Contrato C1 — vencimento 26/07/2026 — valor do empréstimo R$ 100,00."
        )

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.INDEFINIDO, contratos=[])],
            )
            mensagem = self._in(conv, "quero pagar")
            process_mensagem(mensagem.id)

        resposta = self._last_out_texto(conv)
        self.assertEqual(resposta, "O boleto seria de renovação? ou quitação?")
        self.assertNotIn("C1", resposta)

    def test_pagamento_incompleto_nao_repete_contratos_se_na_fila(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            vlr_emprestimo=100.0,
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            # IA diz que quer info de contrato (lista) e pagamento na mesma rodada
            mock_ia.return_value = _classificacao(
                infos_contrato=[InfoContratoPedido(info=InfoContrato.LISTA_CONTRATOS, contratos=[])],
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.INDEFINIDO, contratos=[])],
            )
            mensagem = self._in(conv, "quais meus contratos e quero pagar")
            process_mensagem(mensagem.id)

        mensagens = list(conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em"))
        # A última mensagem enviada deve ser apenas a pergunta
        self.assertEqual(mensagens[-1].texto, "O boleto seria de renovação? ou quitação?")
        # E a mensagem anterior a ela deve conter os detalhes do contrato
        self.assertIn("C1", mensagens[-2].texto)

    def test_renovacao_com_contrato_ja_identificado_nao_repete_lista_so_pergunta_prazo(self):
        # Bug relatado: cliente já viu a lista, escolheu "o mais antigo" (a IA
        # já resolveu pra um contrato específico) -- só falta o prazo, não faz
        # sentido reenviar a lista inteira de novo.
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            vlr_emprestimo=100.0,
        )
        ContratoPenhor.objects.create(
            contrato="C2", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=20),
            vlr_emprestimo=200.0,
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.RENOVAR, contratos=["C1"])],
                pronto_para_criar_solicitacao=False,
            )
            mensagem = self._in(conv, "vou querer renovar o contrato mais antigo")
            process_mensagem(mensagem.id)

        resposta = self._last_out_texto(conv)
        self.assertEqual(
            resposta,
            "Para quantos dias você quer renovar o contrato C1 (30/60/90/120/150/180 dias)?",
        )
        self.assertNotIn("C2", resposta)

    def test_quitar_com_contrato_ja_identificado_nao_repete_lista(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.QUITAR, contratos=["C1"])],
                pronto_para_criar_solicitacao=False,
            )
            mensagem = self._in(conv, "quero quitar o C1")
            process_mensagem(mensagem.id)

        resposta = self._last_out_texto(conv)
        self.assertEqual(resposta, "Você confirma que quer o boleto de quitação do contrato C1?")

    def test_renovacao_com_contrato_ambiguo_ainda_mostra_a_lista(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Carlos Lima")
        ContratoPenhor.objects.create(
            contrato="C1", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            vlr_emprestimo=100.0,
        )
        conv = Conversa.objects.create(
            remote_jid="5567900000004@s.whatsapp.net",
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.RENOVAR, contratos=[])],
                pronto_para_criar_solicitacao=False,
            )
            mensagem = self._in(conv, "quero renovar")
            process_mensagem(mensagem.id)

        resposta = self._last_out_texto(conv)
        self.assertIn("C1", resposta)


class InfoContratoRendererIntegrationTests(WhatsappTasksTestCase):
    def test_info_contrato_identificado_db_fresca_usa_valores_do_banco(self):
        cliente = Cliente.objects.create(cpf="52998224725", nome="Marcia Alves")
        Telefone.objects.create(cliente=cliente, numero="+5567988887777")
        contrato = ContratoPenhor.objects.create(
            contrato="C42",
            cliente=cliente,
            situacao="Contrato Renovado",
            situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=15),
        )
        conv = Conversa.objects.create(
            remote_jid="5567988887777@s.whatsapp.net",
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        esperado = render_template(
            self.msgs.tpl_contrato_vencimento,
            contrato="C42",
            vencimento=formatar_data(contrato.data_vencimento),
        )

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(conv, "quando vence o C42?")
            process_mensagem(mensagem.id)

        texto = self._last_out_texto(conv)
        self.assertEqual(texto, esperado)
        self.assertIn(formatar_data(contrato.data_vencimento), texto)

    def test_info_contrato_multi_contrato_faz_fan_out_de_n_mensagens(self):
        # 2+ contratos -> intro + 1 linha por contrato + totalizador, cada
        # um persistido como uma Mensagem OUT separada (fan-out real).
        cliente = Cliente.objects.create(cpf="11144477735", nome="Fernanda Reis")
        Telefone.objects.create(cliente=cliente, numero="+5567988880000")
        ContratoPenhor.objects.create(
            contrato="C10", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
        )
        ContratoPenhor.objects.create(
            contrato="C11", cliente=cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=20),
        )
        conv = Conversa.objects.create(
            remote_jid="5567988880000@s.whatsapp.net",
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=cliente,
        )
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(conv, "quando vencem meus contratos?")
            process_mensagem(mensagem.id)

        outs = list(
            conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        # "oi" (setup) + intro + 2 linhas + totalizador = 5
        self.assertEqual(len(outs), 5)
        self.assertEqual(outs[0], "oi")
        self.assertIn("C10", outs[2])
        self.assertIn("C11", outs[3])
        ativos_map = {c["contrato"]: c for c in _contratos_ativos_values(cliente)}
        self.assertEqual(
            outs[4],
            _montar_totalizador_geral(["C10", "C11"], ativos_map, self.msgs),
        )
        # 4 mensagens no fan-out (intro + 2 linhas + totalizador) -> 3 pausas
        self.assertEqual(self.mock_sleep.call_count, 3)


class FaqEFallbackTests(WhatsappTasksTestCase):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(cpf="52998224725", nome="Rita Nunes")
        Telefone.objects.create(cliente=self.cliente, numero="+5567977776666")
        self.conv = Conversa.objects.create(
            remote_jid="5567977776666@s.whatsapp.net",
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=self.cliente,
        )
        Mensagem.objects.create(conversa=self.conv, direcao=Mensagem.Direcao.OUT, texto="oi")

    def test_faq_envia_respostas_na_ordem(self):
        faq = FAQ.objects.create(pergunta="Vocês aceitam relógio?", ativo=True)
        FAQResposta.objects.create(faq=faq, ordem=0, texto="Primeira resposta")
        FAQResposta.objects.create(faq=faq, ordem=1, texto="Segunda resposta")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(faq_ids=[faq.id])
            mensagem = self._in(self.conv, "aceita relógio?")
            process_mensagem(mensagem.id)

        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        self.assertEqual(outs, ["oi", "Primeira resposta", "Segunda resposta"])

    def test_fallback_sem_resposta_cria_faq_sugerida_e_marca_revisao(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                duvidas_sem_faq=["Vocês trabalham feriado?"],
            )
            mensagem = self._in(self.conv, "vcs abrem no feriado?")
            process_mensagem(mensagem.id)

        self.conv.refresh_from_db()
        self.assertTrue(self.conv.precisa_revisao_humana)
        self.assertEqual(self._last_out_texto(self.conv), self.msgs.msg_fallback_sem_resposta)
        sugestao = FAQSugerida.objects.get(pergunta="Vocês trabalham feriado?")
        self.assertEqual(sugestao.ocorrencias, 1)
        self.assertEqual(sugestao.status, FAQSugerida.Status.PENDENTE)

    def test_fallback_pergunta_duplicada_incrementa_ocorrencias(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                duvidas_sem_faq=["Vocês trabalham feriado?"],
            )
            m1 = self._in(self.conv, "vcs abrem no feriado?")
            process_mensagem(m1.id)
            m2 = self._in(self.conv, "e no feriado, funciona?")
            process_mensagem(m2.id)

        self.assertEqual(FAQSugerida.objects.filter(pergunta="Vocês trabalham feriado?").count(), 1)
        sugestao = FAQSugerida.objects.get(pergunta="Vocês trabalham feriado?")
        self.assertEqual(sugestao.ocorrencias, 2)


class MultiAcaoLoteTests(WhatsappTasksTestCase):
    """Dispatch sequencial multi-ação (Fase 2/WS-A v3): a IA classifica
    TODAS as solicitações do lote de uma vez (`ClassificacaoLote`) e o
    dispatch acumula uma fila só, enviada ao final via `_enviar_fila` --
    sem esquecer nenhuma ação e sem retornos precoces entre elas."""

    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(cpf="52998224725", nome="Paula Reis")
        Telefone.objects.create(cliente=self.cliente, numero="+5567966665555")
        self.contrato = ContratoPenhor.objects.create(
            contrato="C1", cliente=self.cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            liquidacao="R$ 500,00",
        )
        self.conv = Conversa.objects.create(
            remote_jid="5567966665555@s.whatsapp.net",
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=self.cliente,
        )
        Mensagem.objects.create(conversa=self.conv, direcao=Mensagem.Direcao.OUT, texto="oi")
        self.faq = FAQ.objects.create(pergunta="Vocês abrem sábado?", ativo=True)
        FAQResposta.objects.create(faq=self.faq, ordem=0, texto="Sim, sábado até meio-dia!")

    def test_lote_saudacao_faq_e_quitacao_sai_na_ordem(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                saudacao=True,
                faq_ids=[self.faq.id],
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)],
            )
            mensagem = self._in(self.conv, "bom dia, quanto pra quitar? vcs abrem sábado?")
            process_mensagem(mensagem.id)

        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        # "oi" (setup) + saudação + faq + quitação (1 contrato = 1 linha)
        self.assertEqual(len(outs), 4)
        self.assertIn("Paula", outs[1])
        # Bug relatado: a mesma leva já traz pedido (FAQ + quitação) -> a
        # saudação não deve perguntar "como posso ajudar" à toa.
        self.assertNotIn("posso", outs[1].lower())
        self.assertEqual(outs[2], "Sim, sábado até meio-dia!")
        self.assertIn("C1", outs[3])

    def test_saudacao_sozinha_ainda_pergunta_como_posso_ajudar(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            mensagem = self._in(self.conv, "boa tarde")
            process_mensagem(mensagem.id)

        resposta = self._last_out_texto(self.conv)
        self.assertIn("Paula", resposta)
        self.assertIn("Como posso te ajudar", resposta)

    def test_saudacao_com_info_contrato_nao_pergunta_como_posso_ajudar(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                saudacao=True,
                infos_contrato=[InfoContratoPedido(info=InfoContrato.LISTA_CONTRATOS)],
            )
            mensagem = self._in(self.conv, "boa noite, quantos contratos eu tenho?")
            process_mensagem(mensagem.id)

        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        self.assertIn("Paula", outs[1])
        self.assertNotIn("posso", outs[1].lower())
        self.assertIn("C1", outs[2])

    def test_faq_mais_pagamento_sem_identificacao_faq_sai_e_pede_cpf_uma_vez(self):
        # PHN_<cpf>_<nome> na agenda mas o CPF não existe no cadastro de
        # clientes -> tipo_contato=CLIENTE, cliente=None -> pede CPF (branch
        # "else" do gate; distinto do desconhecido puro, que recebe
        # msg_cadastro_nao_localizado).
        conv = Conversa.objects.create(remote_jid="5567900000020@s.whatsapp.net")
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                faq_ids=[self.faq.id],
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.QUITAR)],
            )
            mensagem = self._in(
                conv, "vcs abrem sábado? quero quitar meu contrato", push_name="PHN_99999999999_Fulano"
            )
            process_mensagem(mensagem.id)

        outs = list(
            conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        self.assertEqual(outs, ["oi", "Sim, sábado até meio-dia!", self.msgs.msg_pedir_cpf])

    def test_gate_db_suprime_infos_mas_faq_sai(self):
        self.bot.ultima_atualizacao_dados = timezone.now() - timedelta(days=10)
        self.bot.freshness_horas = 1
        self.bot.save()
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                faq_ids=[self.faq.id],
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(self.conv, "vcs abrem sábado? quando vence meu contrato?")
            process_mensagem(mensagem.id)

        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        self.assertEqual(outs, ["oi", "Sim, sábado até meio-dia!", self.msgs.msg_db_desatualizada])
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.precisa_revisao_humana)

    def test_duas_faqs_no_mesmo_lote(self):
        faq2 = FAQ.objects.create(pergunta="Aceita relógio?", ativo=True)
        FAQResposta.objects.create(faq=faq2, ordem=0, texto="Aceitamos sim!")
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(faq_ids=[self.faq.id, faq2.id])
            mensagem = self._in(self.conv, "abrem sábado? aceita relógio?")
            process_mensagem(mensagem.id)

        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        self.assertEqual(outs, ["oi", "Sim, sábado até meio-dia!", "Aceitamos sim!"])

    def test_duvidas_sem_faq_com_outra_acao_gera_faqsugerida_por_duvida_e_msg_duvida_anotada(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                saudacao=True,
                duvidas_sem_faq=["Vocês fazem entrega em domicílio?", "Tem estacionamento?"],
            )
            mensagem = self._in(self.conv, "bom dia! fazem entrega? tem estacionamento?")
            process_mensagem(mensagem.id)

        self.assertEqual(FAQSugerida.objects.count(), 2)
        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        # "oi" (setup) + saudação + msg_duvida_anotada
        self.assertEqual(len(outs), 3)
        self.assertIn("Vocês fazem entrega em domicílio?", outs[-1])
        self.assertIn("Tem estacionamento?", outs[-1])
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.precisa_revisao_humana)

    def test_nenhuma_acao_cai_no_fallback(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao()
            mensagem = self._in(self.conv, "ok, obrigado")
            process_mensagem(mensagem.id)

        self.assertEqual(self._last_out_texto(self.conv), self.msgs.msg_fallback_sem_resposta)
        self.assertEqual(FAQSugerida.objects.filter(pergunta_original="ok, obrigado").count(), 1)

    def test_precisa_humano_nao_suprime_acoes(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True, precisa_humano=True)
            mensagem = self._in(self.conv, "bom dia, quero falar com atendente humano")
            process_mensagem(mensagem.id)

        self.assertIn("Paula", self._last_out_texto(self.conv))
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.precisa_revisao_humana)

    def test_filtro_valor_sem_campo_pergunta_1x_e_suprime_o_pedido(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[
                    InfoContratoPedido(info=InfoContrato.LISTA_CONTRATOS, filtro_valor_min=10000, filtro_valor_campo=None)
                ],
            )
            mensagem = self._in(self.conv, "me manda os contratos acima de 10 mil")
            process_mensagem(mensagem.id)

        self.assertEqual(self._last_out_texto(self.conv), self.msgs.msg_pedir_campo_valor_filtro)

    def test_filtro_valor_com_campo_definido_nao_pergunta(self):
        self.contrato.vlr_emprestimo = 15000
        self.contrato.save(update_fields=["vlr_emprestimo"])
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                infos_contrato=[
                    InfoContratoPedido(
                        info=InfoContrato.LISTA_CONTRATOS,
                        filtro_valor_min=10000,
                        filtro_valor_campo=CampoValor.EMPRESTIMO,
                    )
                ],
            )
            mensagem = self._in(self.conv, "me manda os contratos acima de 10 mil de empréstimo")
            process_mensagem(mensagem.id)

        self.assertNotEqual(self._last_out_texto(self.conv), self.msgs.msg_pedir_campo_valor_filtro)
        self.assertIn("C1", self._last_out_texto(self.conv))


class FalsoPositivoCpfTests(WhatsappTasksTestCase):
    def setUp(self):
        super().setUp()
        self.conv = Conversa.objects.create(remote_jid="5567900000005@s.whatsapp.net")
        Mensagem.objects.create(conversa=self.conv, direcao=Mensagem.Direcao.OUT, texto="oi")

    def test_11_digitos_crus_fora_de_aguardando_verificacao_nao_dispara_cpf(self):
        self.conv.estado = Conversa.Estado.NOVA
        self.conv.save()
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            mensagem = self._in(self.conv, "meu contrato eh 12345678901 valeu")
            process_mensagem(mensagem.id)

        texto = self._last_out_texto(self.conv)
        self.assertNotEqual(texto, self.msgs.msg_cpf_invalido)
        self.assertNotEqual(texto, self.msgs.msg_cpf_nao_bate)
        self.conv.refresh_from_db()
        self.assertNotEqual(self.conv.identificacao, Conversa.MetodoIdentificacao.CPF)

    def test_cpf_pontuado_dispara_verificacao_mesmo_fora_de_aguardando(self):
        self.conv.estado = Conversa.Estado.NOVA
        self.conv.save()
        Cliente.objects.create(cpf="52998224725", nome="Sem Telefone Cadastrado")
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            mensagem = self._in(self.conv, "meu cpf eh 529.982.247-25")
            process_mensagem(mensagem.id)

        self.conv.refresh_from_db()
        self.assertEqual(self.conv.identificacao, Conversa.MetodoIdentificacao.CPF)
        self.assertEqual(self.conv.cpf_verificado, "52998224725")

    def test_11_digitos_crus_dentro_de_aguardando_verificacao_dispara_cpf(self):
        self.conv.estado = Conversa.Estado.AGUARDANDO_VERIFICACAO
        self.conv.save()
        Cliente.objects.create(cpf="52998224725", nome="Cliente CPF Cru")
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            mensagem = self._in(self.conv, "52998224725")
            process_mensagem(mensagem.id)

        self.conv.refresh_from_db()
        self.assertEqual(self.conv.identificacao, Conversa.MetodoIdentificacao.CPF)


class LockECoalescenciaTests(WhatsappTasksTestCase):
    def test_conversa_ocupada_reagenda_sem_responder(self):
        conv = Conversa.objects.create(
            remote_jid="5567900000006@s.whatsapp.net",
            processando_desde=timezone.now(),
        )
        mensagem = self._in(conv, "oi")

        with patch("django_q.tasks.schedule") as mock_schedule:
            process_mensagem(mensagem.id)
            mock_schedule.assert_called_once()
            args, kwargs = mock_schedule.call_args
            self.assertEqual(args[0], "whatsapp.tasks.process_mensagem")
            self.assertEqual(args[1], mensagem.id)

        self.mock_client.send_text.assert_not_called()
        self.assertEqual(conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).count(), 0)

    def test_mensagem_superada_por_mais_nova_aborta_sem_responder(self):
        conv = Conversa.objects.create(remote_jid="5567900000007@s.whatsapp.net")
        mais_antiga = self._in(conv, "primeira")
        mais_nova = self._in(conv, "segunda")
        self.assertGreater(mais_nova.criado_em, mais_antiga.criado_em)

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            process_mensagem(mais_antiga.id)

        mock_ia.assert_not_called()
        self.mock_client.send_text.assert_not_called()
        self.assertEqual(conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).count(), 0)


class ResponderEnviadoOkTests(WhatsappTasksTestCase):
    def test_send_text_false_marca_enviado_ok_false_e_revisao(self):
        self.mock_client.send_text.return_value = False
        conv = Conversa.objects.create(remote_jid="5567900000008@s.whatsapp.net")
        mensagem = self._in(conv, "oi")
        process_mensagem(mensagem.id)

        conv.refresh_from_db()
        self.assertTrue(conv.precisa_revisao_humana)
        out = conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).first()
        self.assertIsNotNone(out)
        self.assertEqual(out.enviado_ok, False)


class WebhookExtrairConteudoTests(TestCase):
    def test_conversation(self):
        texto, tipo = _extrair_conteudo({"conversation": "Olá"})
        self.assertEqual((texto, tipo), ("Olá", ""))

    def test_extended_text_message(self):
        texto, tipo = _extrair_conteudo({"extendedTextMessage": {"text": "Oi, tudo bem?"}})
        self.assertEqual((texto, tipo), ("Oi, tudo bem?", ""))

    def test_image_message(self):
        texto, tipo = _extrair_conteudo({"imageMessage": {"caption": "olha essa joia"}})
        self.assertEqual((texto, tipo), ("olha essa joia", "image"))

    def test_video_message(self):
        texto, tipo = _extrair_conteudo({"videoMessage": {"caption": "video de exemplo"}})
        self.assertEqual((texto, tipo), ("video de exemplo", "video"))

    def test_document_message_usa_caption_ou_filename(self):
        texto, tipo = _extrair_conteudo({"documentMessage": {"fileName": "boleto.pdf"}})
        self.assertEqual((texto, tipo), ("boleto.pdf", "document"))
        texto, tipo = _extrair_conteudo(
            {"documentMessage": {"caption": "meu documento", "fileName": "boleto.pdf"}}
        )
        self.assertEqual((texto, tipo), ("meu documento", "document"))

    def test_audio_message(self):
        texto, tipo = _extrair_conteudo({"audioMessage": {}})
        self.assertEqual((texto, tipo), ("", "audio"))

    def test_message_vazia(self):
        self.assertEqual(_extrair_conteudo({}), ("", ""))
        self.assertEqual(_extrair_conteudo(None), ("", ""))


@override_settings(WEBHOOK_TOKEN="test-token-123")
class WhatsappWebhookTestCase(TestCase):
    def _payload(self, remote_jid="5567999999999@s.whatsapp.net", message=None, wa_id="WA1", from_me=False):
        return {
            "data": {
                "key": {"remoteJid": remote_jid, "id": wa_id, "fromMe": from_me},
                "pushName": "Fulano",
                "message": message or {"conversation": "oi"},
            }
        }

    def _post(self, payload, token="test-token-123"):
        return self.client.post(
            reverse("whatsapp:webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_WEBHOOK_TOKEN=token,
        )

    @patch("whatsapp.views.async_task")
    def test_token_invalido_rejeitado(self, mock_async_task):
        response = self._post(self._payload(), token="token-errado")
        self.assertEqual(response.status_code, 403)
        mock_async_task.assert_not_called()
        self.assertEqual(Mensagem.objects.count(), 0)

    @patch("whatsapp.views.async_task")
    def test_imagem_persiste_tipo_midia_image(self, mock_async_task):
        payload = self._payload(
            wa_id="WA-IMG-1",
            message={"imageMessage": {"caption": "olha essa joia"}},
        )
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        mensagem = Mensagem.objects.get(wa_message_id="WA-IMG-1")
        self.assertEqual(mensagem.tipo_midia, "image")
        self.assertEqual(mensagem.texto, "olha essa joia")
        mock_async_task.assert_called_once_with("whatsapp.tasks.process_mensagem", mensagem.id)

    @patch("whatsapp.views.async_task")
    def test_dedup_por_wa_message_id(self, mock_async_task):
        payload = self._payload(wa_id="WA-DUP-1")
        first = self._post(payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(Mensagem.objects.filter(wa_message_id="WA-DUP-1").count(), 1)

        second = self._post(payload)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json().get("reason"), "duplicate")
        self.assertEqual(Mensagem.objects.filter(wa_message_id="WA-DUP-1").count(), 1)
        # async_task só foi enfileirado na primeira vez.
        mock_async_task.assert_called_once()

    @patch("whatsapp.views.async_task")
    def test_grupo_e_ignorado(self, mock_async_task):
        payload = self._payload(remote_jid="12345-6789@g.us", wa_id="WA-GROUP-1")
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("reason"), "group")
        self.assertEqual(Mensagem.objects.count(), 0)
        mock_async_task.assert_not_called()


class RespostasContratoUnitTests(TestCase):
    def test_formatar_moeda(self):
        self.assertEqual(formatar_moeda(1234.5), "R$ 1.234,50")
        self.assertEqual(formatar_moeda(1000000), "R$ 1.000.000,00")
        self.assertEqual(formatar_moeda(-50), "-R$ 50,00")
        self.assertEqual(formatar_moeda(None), "(valor não informado)")

    def test_formatar_data(self):
        self.assertEqual(formatar_data(None), "(data não informada)")
        self.assertEqual(formatar_data(timezone.datetime(2026, 3, 5).date()), "05/03/2026")

    def test_render_template_placeholder_desconhecido_nao_explode(self):
        resultado = render_template("Olá {nome}, seu contrato {contrato} está ok", nome="Ana")
        self.assertIn("Ana", resultado)
        self.assertIn("{contrato}", resultado)  # preservado, não levanta

    def test_render_template_vazio(self):
        self.assertEqual(render_template("", nome="Ana"), "")

    def test_formatar_peso(self):
        self.assertEqual(formatar_peso(Decimal("16.30")), "16,30 g")
        self.assertEqual(formatar_peso(None), "(peso não informado)")

    def test_limpar_peso_do_laudo_remove_trecho_redundante(self):
        laudo = (
            "UM COLAR, DE: OURO; CONSTAM: amolgada(s), PESO LOTE: 16,30G "
            "(DEZESSEIS GRAMAS E TRINTA CENTIGRAMAS)"
        )
        resultado = _limpar_peso_do_laudo(laudo)
        self.assertNotIn("PESO LOTE", resultado)
        self.assertNotIn("CENTIGRAMAS", resultado)
        self.assertIn("UM COLAR, DE: OURO; CONSTAM: amolgada(s)", resultado)

    def test_limpar_peso_do_laudo_tolerante_sem_padrao(self):
        # Sem o padrão "PESO LOTE: ...G (...)" -> devolve o texto original.
        self.assertEqual(_limpar_peso_do_laudo("Anel de ouro simples"), "Anel de ouro simples")
        self.assertEqual(_limpar_peso_do_laudo(""), "")
        self.assertIsNone(_limpar_peso_do_laudo(None))


class MontarTotalizadorGeralTests(TestCase):
    def setUp(self):
        self.msgs = MensagensConfig.get_solo()

    def test_soma_avaliacao_emprestimo_e_renovacao_por_prazo_disponivel(self):
        ativos_map = {
            "C1": {"vlr_avaliacao": Decimal("1000"), "vlr_emprestimo": Decimal("500"), "vlr_renovacao_30": Decimal("100")},
            "C2": {"vlr_avaliacao": Decimal("2000"), "vlr_emprestimo": Decimal("800"), "vlr_renovacao_30": Decimal("150"), "vlr_renovacao_60": Decimal("300")},
        }
        resultado = _montar_totalizador_geral(["C1", "C2"], ativos_map, self.msgs)
        self.assertIn("R$ 3.000,00", resultado)  # avaliação
        self.assertIn("R$ 1.300,00", resultado)  # empréstimo
        self.assertIn("30 dias: R$ 250,00", resultado)
        self.assertIn("60 dias: R$ 300,00", resultado)
        self.assertNotIn("90 dias", resultado)

    def test_sem_nenhum_valor_de_renovacao_nao_mostra_secao_de_prazos(self):
        ativos_map = {"C1": {"vlr_avaliacao": None, "vlr_emprestimo": None}}
        resultado = _montar_totalizador_geral(["C1"], ativos_map, self.msgs)
        self.assertNotIn("Renovação total por prazo", resultado)
        self.assertIn("R$ 0,00", resultado)


class RenderizarInfosContratoTests(TestCase):
    """`renderizar_infos_contrato` retorna `list[str]` (fan-out): 1 contrato
    reportado -> lista de 1 item (sem intro/totalizador); 2+ -> intro
    (`tpl_lista_header`) + 1 linha por contrato + totalizador
    (`tpl_totalizador`/`tpl_totalizador_geral`)."""

    def setUp(self):
        self.msgs = MensagensConfig.get_solo()
        self.cliente = Cliente.objects.create(cpf="52998224725", nome="Beatriz Costa")

    def _contrato(self, **kwargs):
        defaults = dict(
            cliente=self.cliente,
            situacao="Contrato Renovado",
            situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=20),
        )
        defaults.update(kwargs)
        return ContratoPenhor.objects.create(**defaults)

    def test_sem_cliente_retorna_mensagem_sem_contratos(self):
        resultado = renderizar_infos_contrato(None, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertEqual(resultado, [self.msgs.msg_sem_contratos_ativos])

    def test_sem_contratos_ativos_retorna_mensagem_padrao(self):
        # cliente sem nenhum ContratoPenhor
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertEqual(resultado, [self.msgs.msg_sem_contratos_ativos])

    def test_vencimento(self):
        c = self._contrato(contrato="C1")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertEqual(len(resultado), 1)
        self.assertIn("C1", resultado[0])
        self.assertIn(formatar_data(c.data_vencimento), resultado[0])

    def test_renovacao_com_prazo_informado(self):
        self._contrato(contrato="C1", vlr_renovacao_60=1500)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=60)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("R$ 1.500,00", texto)
        self.assertIn("60", texto)
        self.assertNotIn("prazo padrão", texto)

    def test_renovacao_sem_prazo_retorna_todas_opcoes_disponiveis(self):
        self._contrato(
            contrato="C1",
            vlr_renovacao_30=1000,
            vlr_renovacao_60=1500,
        )
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("Renovação 30 dias: R$ 1.000,00", texto)
        self.assertIn("Renovação 60 dias: R$ 1.500,00", texto)
        self.assertNotIn("prazo padrão", texto)

    def test_renovacao_prazo_45_mapeia_para_mais_proximo(self):
        # |45-30|=15 == |45-60|=15 -> empate resolvido pelo primeiro (30).
        self._contrato(contrato="C1", vlr_renovacao_30=999, vlr_renovacao_60=1999)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=45)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("R$ 999,00", texto)
        self.assertNotIn("R$ 1.999,00", texto)

    def test_renovacao_prazo_100_mapeia_para_90(self):
        self._contrato(contrato="C1", vlr_renovacao_90=2500, vlr_renovacao_120=3000)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=100)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("R$ 2.500,00", texto)
        self.assertIn("90", texto)

    def test_quitacao_usa_campo_liquidacao_do_erp(self):
        # Quitação vem do campo texto `liquidacao` do ERP (já formatado),
        # NUNCA de vlr_liquido (valor recebido na contratação).
        self._contrato(contrato="C1", liquidacao="R$850,00", vlr_liquido=999)
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)], self.msgs)
        self.assertEqual(len(resultado), 1)
        texto = resultado[0]
        self.assertIn("C1", texto)
        self.assertIn("R$ 850,00", texto)
        self.assertIn("Liquidação:", texto)
        self.assertNotIn("999", texto)

    def test_quitacao_sem_liquidacao_avisa_indisponivel(self):
        self._contrato(contrato="C1", liquidacao="")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)], self.msgs)
        self.assertIn("indisponível", resultado[0])

    def test_parcela_pula_contrato_nao_parcelado(self):
        self._contrato(contrato="C1", parcelado=False, vlr_parcela=100)
        self._contrato(contrato="C2", parcelado=True, vlr_parcela=200)
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_PARCELA)], self.msgs)
        # só 1 contrato parcelado -> sem intro/totalizador, lista de 1 item.
        self.assertEqual(len(resultado), 1)
        self.assertIn("C2", resultado[0])
        self.assertIn("R$ 200,00", resultado[0])
        self.assertNotIn("C1", resultado[0])
        self.assertNotIn("R$ 100,00", resultado[0])

    def test_multi_contrato_usa_intro_e_totalizador(self):
        self._contrato(contrato="C1")
        self._contrato(contrato="C2")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        # sequência: intro -> 1 linha por contrato -> totalizador
        self.assertEqual(len(resultado), 4)
        self.assertEqual(resultado[0], self.msgs.tpl_intro_vencimento)
        self.assertIn("C1", resultado[1])
        self.assertIn("C2", resultado[2])
        ativos_map = {c["contrato"]: c for c in _contratos_ativos_values(self.cliente)}
        self.assertEqual(resultado[3], _montar_totalizador_geral(["C1", "C2"], ativos_map, self.msgs))

    def test_um_unico_contrato_retorna_lista_de_um_item_sem_intro_totalizador(self):
        self._contrato(contrato="C1")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertEqual(len(resultado), 1)
        self.assertNotEqual(resultado[0], render_template(self.msgs.tpl_lista_header, nome="Beatriz", qtd=1))

    def test_lista_e_detalhe_usam_template_resumo(self):
        self._contrato(contrato="C1", vlr_emprestimo=500)
        for info in (InfoContrato.LISTA_CONTRATOS, InfoContrato.DETALHE_CONTRATO):
            resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=info)], self.msgs)
            self.assertEqual(len(resultado), 1)
            self.assertIn("C1", resultado[0])
            self.assertIn("R$ 500,00", resultado[0])

    def test_laudo_contrato(self):
        self._contrato(contrato="C1", laudo="Anel de ouro com diamante de 18k")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.LAUDO)], self.msgs)
        self.assertEqual(len(resultado), 1)
        self.assertIn("C1", resultado[0])
        self.assertIn("Anel de ouro com diamante de 18k", resultado[0])

    def test_laudo_inclui_peso_e_valor_avaliacao_e_remove_peso_duplicado_do_texto(self):
        laudo_erp = (
            "UM COLAR, DE: OURO; CONSTAM: amolgada(s), PESO LOTE: 16,30G "
            "(DEZESSEIS GRAMAS E TRINTA CENTIGRAMAS)"
        )
        self._contrato(contrato="C1", laudo=laudo_erp, peso=Decimal("16.30"), vlr_avaliacao=Decimal("5000.00"))
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.LAUDO)], self.msgs)
        self.assertEqual(len(resultado), 1)
        texto = resultado[0]
        self.assertIn("16,30 g", texto)
        self.assertIn("R$ 5.000,00", texto)
        self.assertIn("UM COLAR, DE: OURO; CONSTAM: amolgada(s)", texto)
        self.assertNotIn("PESO LOTE", texto)

    def test_laudo_com_peso_e_avaliacao_nulos_nao_levanta(self):
        self._contrato(contrato="C1", laudo="Anel de ouro", peso=None, vlr_avaliacao=None)
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.LAUDO)], self.msgs)
        texto = resultado[0]
        self.assertIn("(peso não informado)", texto)
        self.assertIn("(valor não informado)", texto)

    # --- Mesclagem por contrato: pedidos múltiplos viram 1 msg/contrato -----

    def test_dois_pedidos_nao_numericos_mesclam_por_contrato(self):
        self._contrato(contrato="C1", laudo="Colar de ouro")
        self._contrato(contrato="C2", laudo="Anel de prata")
        self._contrato(contrato="C3", laudo="Pulseira de ouro")
        pedidos = [
            InfoContratoPedido(info=InfoContrato.LISTA_CONTRATOS),
            InfoContratoPedido(info=InfoContrato.LAUDO),
        ]
        resultado = renderizar_infos_contrato(self.cliente, pedidos, self.msgs)
        # intro + 3 mensagens mescladas (resumo + laudo juntos) + 1 totalizador geral só
        self.assertEqual(len(resultado), 5)
        self.assertEqual(resultado[0], render_template(self.msgs.tpl_lista_header, qtd=3))
        self.assertIn("C1", resultado[1])
        self.assertIn("Colar de ouro", resultado[1])
        self.assertIn("C2", resultado[2])
        self.assertIn("Anel de prata", resultado[2])
        self.assertIn("C3", resultado[3])
        self.assertIn("Pulseira de ouro", resultado[3])
        ativos_map = {c["contrato"]: c for c in _contratos_ativos_values(self.cliente)}
        self.assertEqual(resultado[4], _montar_totalizador_geral(["C1", "C2", "C3"], ativos_map, self.msgs))

    def test_pedido_numerico_mais_nao_numerico_nao_empilha_totalizador_geral(self):
        self._contrato(contrato="C1", liquidacao="R$ 1.000,00", laudo="Colar de ouro")
        self._contrato(contrato="C2", liquidacao="R$ 2.000,00", laudo="Anel de prata")
        pedidos = [
            InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO),
            InfoContratoPedido(info=InfoContrato.LAUDO),
        ]
        resultado = renderizar_infos_contrato(self.cliente, pedidos, self.msgs)
        # intro + 2 mensagens mescladas + só o totalizador de quitação (sem o geral)
        self.assertEqual(len(resultado), 4)
        self.assertIn("Colar de ouro", resultado[1])
        self.assertIn("R$ 3.000,00", resultado[3])
        self.assertNotIn("Total avaliado", resultado[3])

    def test_dois_pedidos_numericos_sem_detalhado_geram_so_dois_totalizadores(self):
        # Padrão (detalhado=False): sem listar contrato por contrato, só o
        # resumo de cada tipo pedido.
        self._contrato(contrato="C1", liquidacao="R$ 1.000,00", parcelado=True, vlr_parcela=100)
        self._contrato(contrato="C2", liquidacao="R$ 2.000,00", parcelado=True, vlr_parcela=200)
        pedidos = [
            InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO),
            InfoContratoPedido(info=InfoContrato.VALOR_PARCELA),
        ]
        resultado = renderizar_infos_contrato(self.cliente, pedidos, self.msgs)
        self.assertEqual(len(resultado), 2)
        self.assertIn("R$ 3.000,00", resultado[0])
        self.assertIn("R$ 300,00", resultado[1])

    def test_dois_pedidos_numericos_detalhado_geram_intro_linhas_e_totalizadores(self):
        self._contrato(contrato="C1", liquidacao="R$ 1.000,00", parcelado=True, vlr_parcela=100)
        self._contrato(contrato="C2", liquidacao="R$ 2.000,00", parcelado=True, vlr_parcela=200)
        pedidos = [
            InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO, detalhado=True),
            InfoContratoPedido(info=InfoContrato.VALOR_PARCELA, detalhado=True),
        ]
        resultado = renderizar_infos_contrato(self.cliente, pedidos, self.msgs)
        # intro + 2 mensagens mescladas + totalizador de quitação + totalizador de parcela
        self.assertEqual(len(resultado), 5)
        self.assertIn("R$ 3.000,00", resultado[3])
        self.assertIn("R$ 300,00", resultado[4])

    def test_um_unico_contrato_com_dois_pedidos_retorna_uma_mensagem_so(self):
        self._contrato(contrato="C1", laudo="Colar de ouro")
        pedidos = [
            InfoContratoPedido(info=InfoContrato.LISTA_CONTRATOS),
            InfoContratoPedido(info=InfoContrato.LAUDO),
        ]
        resultado = renderizar_infos_contrato(self.cliente, pedidos, self.msgs)
        self.assertEqual(len(resultado), 1)
        self.assertIn("C1", resultado[0])
        self.assertIn("Colar de ouro", resultado[0])

    def test_pedido_com_filtro_parcial_so_soma_ao_contrato_alvo(self):
        self._contrato(contrato="C1", laudo="Colar de ouro")
        self._contrato(contrato="C2", laudo="Anel de prata")
        pedidos = [
            InfoContratoPedido(info=InfoContrato.LAUDO, contratos=["C1"]),
            InfoContratoPedido(info=InfoContrato.VENCIMENTO),
        ]
        resultado = renderizar_infos_contrato(self.cliente, pedidos, self.msgs)
        texto_c1 = next(m for m in resultado if "C1" in m)
        texto_c2 = next(m for m in resultado if "C2" in m)
        self.assertIn("Colar de ouro", texto_c1)
        self.assertNotIn("Anel de prata", texto_c2)
        self.assertNotIn("Colar de ouro", texto_c2)

    # --- Filtros: vencido / valor -------------------------------------------

    def test_filtro_vencido_so_inclui_contratos_com_data_passada(self):
        self._contrato(contrato="C1", data_vencimento=timezone.localdate() - timedelta(days=5))
        self._contrato(contrato="C2", data_vencimento=timezone.localdate() + timedelta(days=20))
        pedido = InfoContratoPedido(info=InfoContrato.VENCIMENTO, filtro_vencido=True)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("C1", texto)
        self.assertNotIn("C2", texto)

    def test_filtro_vencido_sem_nenhum_vencido_retorna_sem_contratos(self):
        self._contrato(contrato="C1", data_vencimento=timezone.localdate() + timedelta(days=20))
        pedido = InfoContratoPedido(info=InfoContrato.VENCIMENTO, filtro_vencido=True)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        self.assertEqual(resultado, [self.msgs.msg_sem_contratos_ativos])

    def test_filtro_valor_min_emprestimo_filtra_contratos_abaixo(self):
        self._contrato(contrato="C1", vlr_emprestimo=Decimal("15000"))
        self._contrato(contrato="C2", vlr_emprestimo=Decimal("5000"))
        pedido = InfoContratoPedido(
            info=InfoContrato.LISTA_CONTRATOS, filtro_valor_min=10000, filtro_valor_campo=CampoValor.EMPRESTIMO
        )
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("C1", texto)
        self.assertNotIn("C2", texto)

    def test_filtro_valor_campo_avaliacao_usa_vlr_avaliacao(self):
        self._contrato(contrato="C1", vlr_emprestimo=Decimal("5000"), vlr_avaliacao=Decimal("15000"))
        self._contrato(contrato="C2", vlr_emprestimo=Decimal("15000"), vlr_avaliacao=Decimal("5000"))
        pedido = InfoContratoPedido(
            info=InfoContrato.LISTA_CONTRATOS, filtro_valor_min=10000, filtro_valor_campo=CampoValor.AVALIACAO
        )
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("C1", texto)
        self.assertNotIn("C2", texto)

    def test_filtro_valor_max_filtra_contratos_acima(self):
        self._contrato(contrato="C1", vlr_emprestimo=Decimal("15000"))
        self._contrato(contrato="C2", vlr_emprestimo=Decimal("5000"))
        pedido = InfoContratoPedido(
            info=InfoContrato.LISTA_CONTRATOS, filtro_valor_max=10000, filtro_valor_campo=CampoValor.EMPRESTIMO
        )
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        texto = "\n".join(resultado)
        self.assertIn("C2", texto)
        self.assertNotIn("C1", texto)

    def test_filtro_valor_sem_campo_definido_ignora_filtro_no_renderer(self):
        # Ambiguidade de campo já deveria ter sido resolvida pelo dispatch
        # (whatsapp.tasks) antes de chegar aqui; o renderer nunca quebra --
        # se chegar sem campo definido, simplesmente não filtra por valor.
        self._contrato(contrato="C1", vlr_emprestimo=Decimal("5000"))
        pedido = InfoContratoPedido(info=InfoContrato.LISTA_CONTRATOS, filtro_valor_min=10000, filtro_valor_campo=None)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        self.assertIn("C1", "\n".join(resultado))

    # --- Totalizador: soma dos valores + quantidade -------------------------

    def test_totalizador_renovacao_soma_valores(self):
        self._contrato(contrato="C1", vlr_renovacao_30=1000)
        self._contrato(contrato="C2", vlr_renovacao_30=2000)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=30)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        totalizador = resultado[-1]
        self.assertIn("R$ 3.000,00", totalizador)
        self.assertEqual(totalizador, render_template(self.msgs.tpl_totalizador, qtd=2, total="R$ 3.000,00"))

    def test_totalizador_parcela_soma_so_parcelados(self):
        self._contrato(contrato="C1", parcelado=True, vlr_parcela=100)
        self._contrato(contrato="C2", parcelado=True, vlr_parcela=250)
        self._contrato(contrato="C3", parcelado=False, vlr_parcela=999)
        resultado = renderizar_infos_contrato(
            self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_PARCELA, detalhado=True)], self.msgs
        )
        totalizador = resultado[-1]
        self.assertIn("R$ 350,00", totalizador)
        self.assertNotIn("999", "\n".join(resultado))
        # C3 não é parcelado -> 2 linhas + intro + totalizador = 4
        self.assertEqual(len(resultado), 4)

    def test_totalizador_quitacao_soma_valores_texto_do_erp(self):
        # "R$ 1.813,70" (com espaço) e "R$4.448,60" (sem espaço) -- ambos os
        # formatos que o ERP legado produz.
        self._contrato(contrato="C1", liquidacao="R$ 1.813,70")
        self._contrato(contrato="C2", liquidacao="R$4.448,60")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)], self.msgs)
        totalizador = resultado[-1]
        self.assertIn("R$ 6.262,30", totalizador)
        self.assertNotIn("indisponível", totalizador)
        self.assertNotIn("não somei", totalizador)

    def test_totalizador_quitacao_parcial_indisponivel_soma_resto_com_aviso(self):
        self._contrato(contrato="C1", liquidacao="R$ 1.813,70")
        self._contrato(contrato="C2", liquidacao="")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)], self.msgs)
        totalizador = resultado[-1]
        self.assertIn("R$ 1.813,70", totalizador)
        self.assertIn("não somei 1 contrato(s) com valor de quitação indisponível", totalizador)

    def test_totalizador_quitacao_todos_indisponiveis_usa_totalizador_geral(self):
        self._contrato(contrato="C1", liquidacao="")
        self._contrato(contrato="C2", liquidacao="")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)], self.msgs)
        totalizador = resultado[-1]
        ativos_map = {c["contrato"]: c for c in _contratos_ativos_values(self.cliente)}
        base_esperada = _montar_totalizador_geral(["C1", "C2"], ativos_map, self.msgs)
        self.assertTrue(totalizador.startswith(base_esperada))
        self.assertIn("não somei 2 contrato(s) com valor de quitação indisponível", totalizador)


class EnviarFilaTests(TestCase):
    """`_enviar_fila`: pausa PAUSA_FANOUT entre mensagens (n-1 pausas),
    "toca" o mutex a cada envio, e colapsa o excedente acima do teto
    MAX_MENSAGENS_TURNO preservando o primeiro e o último item da fila."""

    def setUp(self):
        self.conv = Conversa.objects.create(remote_jid="5567900000010@s.whatsapp.net")

    @patch("whatsapp.tasks.time.sleep")
    def test_pausa_n_menos_um_vezes_entre_mensagens(self, mock_sleep):
        enviados = []
        _enviar_fila(["a", "b", "c"], enviados.append, lambda *a, **k: None, self.conv)

        self.assertEqual(enviados, ["a", "b", "c"])
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(PAUSA_FANOUT)

    @patch("whatsapp.tasks.time.sleep")
    def test_um_unico_item_nao_pausa(self, mock_sleep):
        enviados = []
        _enviar_fila(["único"], enviados.append, lambda *a, **k: None, self.conv)
        mock_sleep.assert_not_called()

    @patch("whatsapp.tasks.time.sleep")
    def test_toca_processando_desde_a_cada_envio(self, mock_sleep):
        antes = timezone.now() - timedelta(minutes=5)
        self.conv.processando_desde = antes
        self.conv.save(update_fields=["processando_desde"])

        _enviar_fila(["a", "b"], lambda t: None, lambda *a, **k: None, self.conv)

        self.conv.refresh_from_db()
        self.assertIsNotNone(self.conv.processando_desde)
        self.assertGreater(self.conv.processando_desde, antes)

    @patch("whatsapp.tasks.time.sleep")
    def test_teto_12_colapsa_excedente_preservando_intro_e_totalizador(self, mock_sleep):
        fila = ["intro"] + [f"linha {i}" for i in range(15)] + ["totalizador"]
        enviados = []
        _enviar_fila(fila, enviados.append, lambda *a, **k: None, self.conv)

        self.assertLessEqual(len(enviados), MAX_MENSAGENS_TURNO)
        self.assertEqual(enviados[0], "intro")
        self.assertEqual(enviados[-1], "totalizador")
        # a mensagem colapsada (penúltima) deve conter as linhas excedentes
        self.assertIn("linha 14", enviados[-2])
        self.assertIn("linha 0", "\n".join(enviados))  # nenhuma linha foi perdida

    @patch("whatsapp.tasks.time.sleep")
    def test_fila_dentro_do_teto_nao_colapsa(self, mock_sleep):
        fila = [f"item {i}" for i in range(MAX_MENSAGENS_TURNO)]
        enviados = []
        _enviar_fila(fila, enviados.append, lambda *a, **k: None, self.conv)
        self.assertEqual(enviados, fila)

    @patch("whatsapp.tasks.time.sleep")
    def test_arquivos_na_fila_nunca_sao_colapsados(self, mock_sleep):
        fila = [f"linha {i}" for i in range(14)] + [("caminho.pdf", "boleto.pdf", "legenda")]
        enviados = []
        arquivos = []
        _enviar_fila(
            fila,
            enviados.append,
            lambda caminho, nome, legenda="": arquivos.append((caminho, nome, legenda)),
            self.conv,
        )
        # não colapsa (fila tem item não-string) -> todos os 15 itens são enviados.
        self.assertEqual(len(enviados) + len(arquivos), 15)
        self.assertEqual(arquivos, [("caminho.pdf", "boleto.pdf", "legenda")])


class DebounceZeroTests(WhatsappTasksTestCase):
    """`debounce_segundos=0` (default do setUp da base) é o kill-switch: o
    processamento continua 100% síncrono, sem nunca criar um Schedule."""

    def test_debounce_zero_processa_sincrono_sem_schedule(self):
        conv = Conversa.objects.create(remote_jid="5567900000040@s.whatsapp.net")
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            mensagem = self._in(conv, "bom dia")
            process_mensagem(mensagem.id)

        mock_ia.assert_called_once()
        self.mock_client.send_text.assert_called_once()
        self.assertFalse(Schedule.objects.filter(name=f"pz-debounce-{conv.id}").exists())
        mensagem.refresh_from_db()
        self.assertIsNotNone(mensagem.respondida_em)


class DebounceTests(WhatsappTasksTestCase):
    """Fase 3 (debounce): com `debounce_segundos > 0`, a IA só é chamada
    quando o cliente completa aquele silêncio (ou o Schedule agendado por
    `_agendar_debounce` acorda e encontra o silêncio já cumprido). Respostas
    determinísticas (CPF, saudação de 1º contato, mídia sozinha) continuam
    imediatas e marcam só a mensagem que cobriram; o dispatch via IA marca
    todo o lote de uma vez."""

    def setUp(self):
        super().setUp()
        self.bot.debounce_segundos = 120
        self.bot.save()
        self.cliente = Cliente.objects.create(cpf="52998224725", nome="Paula Reis")
        Telefone.objects.create(cliente=self.cliente, numero="+5567966665555")
        self.contrato = ContratoPenhor.objects.create(
            contrato="C1", cliente=self.cliente, situacao="Contrato Renovado", situacao_codigo="RN",
            data_vencimento=timezone.localdate() + timedelta(days=10),
            liquidacao="R$ 500,00",
        )
        self.conv = Conversa.objects.create(
            remote_jid="5567966665555@s.whatsapp.net",
            identificacao=Conversa.MetodoIdentificacao.TELEFONE,
            tipo_contato=Conversa.TipoContato.CLIENTE,
            cliente=self.cliente,
        )
        Mensagem.objects.create(conversa=self.conv, direcao=Mensagem.Direcao.OUT, texto="oi")

    def _envelhecer(self, *mensagens, segundos=200):
        ids = [m.pk for m in mensagens]
        Mensagem.objects.filter(pk__in=ids).update(
            criado_em=timezone.now() - timedelta(seconds=segundos)
        )

    # --- process_mensagem: agenda em vez de chamar a IA na hora ------------

    def test_mensagem_recente_agenda_schedule_sem_chamar_ia(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mensagem = self._in(self.conv, "quanto pra quitar?")
            process_mensagem(mensagem.id)

        mock_ia.assert_not_called()
        self.mock_client.send_text.assert_not_called()
        sched = Schedule.objects.get(name=f"pz-debounce-{self.conv.id}")
        self.assertEqual(sched.func, "whatsapp.tasks.process_lote_conversa")
        self.assertEqual(sched.args, str(self.conv.id))
        esperado = mensagem.criado_em + timedelta(seconds=120)
        self.assertAlmostEqual(sched.next_run, esperado, delta=timedelta(seconds=5))

    def test_segunda_mensagem_atualiza_mesmo_schedule(self):
        with patch("whatsapp.tasks.extrair_intencao"):
            m1 = self._in(self.conv, "oi, tudo bem?")
            process_mensagem(m1.id)
            m2 = self._in(self.conv, "quanto pra quitar?")
            process_mensagem(m2.id)

        self.assertEqual(Schedule.objects.filter(name=f"pz-debounce-{self.conv.id}").count(), 1)
        sched = Schedule.objects.get(name=f"pz-debounce-{self.conv.id}")
        esperado = m2.criado_em + timedelta(seconds=120)
        self.assertAlmostEqual(sched.next_run, esperado, delta=timedelta(seconds=5))

    # --- lote só coleta o que ainda não foi marcado -------------------------

    def test_lote_ignora_mensagem_ja_marcada_respondida(self):
        antiga = self._in(self.conv, "mensagem já coberta antes")
        antiga.respondida_em = timezone.now()
        antiga.save(update_fields=["respondida_em"])
        pendente = self._in(self.conv, "quanto pra quitar?")

        self.assertEqual(list(_mensagens_pendentes(self.conv)), [pendente])

    # --- process_lote_conversa: recheck de silêncio dentro do lock --------

    def test_process_lote_conversa_silencio_insuficiente_reagenda_sem_ia(self):
        self._in(self.conv, "quanto pra quitar?")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            process_lote_conversa(self.conv.id)

        mock_ia.assert_not_called()
        self.mock_client.send_text.assert_not_called()
        sched = Schedule.objects.get(name=f"pz-debounce-{self.conv.id}")
        self.assertGreater(sched.next_run, timezone.now())

    def test_process_lote_conversa_silencio_suficiente_chama_ia_com_lote_completo(self):
        m1 = self._in(self.conv, "msg1")
        m2 = self._in(self.conv, "msg2")
        # Chamadas separadas (staggered): uma única bulk update daria o
        # MESMO `criado_em` às duas, deixando a ordem do lote sujeita a
        # empate.
        self._envelhecer(m1, segundos=200)
        self._envelhecer(m2, segundos=190)

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            process_lote_conversa(self.conv.id)

        mock_ia.assert_called_once()
        args, kwargs = mock_ia.call_args
        self.assertEqual(args[0], ["msg1", "msg2"])
        self.mock_client.send_text.assert_called_once()
        m1.refresh_from_db()
        m2.refresh_from_db()
        self.assertIsNotNone(m1.respondida_em)
        self.assertIsNotNone(m2.respondida_em)

    def test_process_lote_conversa_bot_inativo_marca_revisao_sem_ia(self):
        self.bot.ativo = False
        self.bot.save()
        conv = Conversa.objects.create(remote_jid="5567900000041@s.whatsapp.net")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            process_lote_conversa(conv.id)

        mock_ia.assert_not_called()
        conv.refresh_from_db()
        self.assertTrue(conv.precisa_revisao_humana)

    # --- determinísticos marcam a mensagem (ou o lote todo) que cobriram --

    def test_cpf_invalido_marca_mensagem_sem_agendar(self):
        conv = Conversa.objects.create(remote_jid="5567900000042@s.whatsapp.net")
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mensagem = self._in(conv, "meu cpf é 111.111.111-11")
            process_mensagem(mensagem.id)

        mock_ia.assert_not_called()
        mensagem.refresh_from_db()
        self.assertIsNotNone(mensagem.respondida_em)
        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_cpf_invalido)
        self.assertFalse(Schedule.objects.filter(name=f"pz-debounce-{conv.id}").exists())

    def test_midia_unica_pendente_marca_e_responde_na_hora(self):
        conv = Conversa.objects.create(remote_jid="5567900000043@s.whatsapp.net")
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")
        mensagem = Mensagem.objects.create(
            conversa=conv, direcao=Mensagem.Direcao.IN, tipo_midia=Mensagem.TipoMidia.IMAGE, texto="",
        )

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            process_mensagem(mensagem.id)

        mock_ia.assert_not_called()
        mensagem.refresh_from_db()
        self.assertIsNotNone(mensagem.respondida_em)
        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_midia_nao_suportada)

    def test_midia_com_texto_pendente_no_lote_nao_responde_e_marca_so_a_midia(self):
        texto_msg = self._in(self.conv, "quanto pra quitar?")
        midia_msg = Mensagem.objects.create(
            conversa=self.conv, direcao=Mensagem.Direcao.IN, tipo_midia=Mensagem.TipoMidia.IMAGE, texto="",
        )

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            process_mensagem(midia_msg.id)

        mock_ia.assert_not_called()
        midia_msg.refresh_from_db()
        texto_msg.refresh_from_db()
        self.assertIsNotNone(midia_msg.respondida_em)
        self.assertIsNone(texto_msg.respondida_em)
        self.assertNotEqual(self._last_out_texto(self.conv), self.msgs.msg_midia_nao_suportada)
        # não retorna sem agendar -- segue até o ponto de decisão do debounce.
        self.assertTrue(Schedule.objects.filter(name=f"pz-debounce-{self.conv.id}").exists())

    def test_saudacao_primeiro_contato_marca_mensagem_sem_ia(self):
        conv = Conversa.objects.create(remote_jid="5567900000044@s.whatsapp.net")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mensagem = self._in(conv, "oi")
            process_mensagem(mensagem.id)

        mock_ia.assert_not_called()
        mensagem.refresh_from_db()
        self.assertIsNotNone(mensagem.respondida_em)

    # --- caso do dono: CPF válido + pergunta 10s depois --------------------

    def test_cpf_valido_depois_pergunta_uma_chamada_ia_com_lote_completo(self):
        conv = Conversa.objects.create(remote_jid="5567900000045@s.whatsapp.net")
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto="oi")

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia_cpf:
            m_cpf = self._in(conv, "529.982.247-25")
            process_mensagem(m_cpf.id)
        mock_ia_cpf.assert_not_called()
        m_cpf.refresh_from_db()
        # CPF válido não vira ação: a mensagem NÃO é marcada -- fica no lote
        # como contexto (o prompt manda ignorar CPF isolado).
        self.assertIsNone(m_cpf.respondida_em)
        conv.refresh_from_db()
        self.assertEqual(conv.identificacao, Conversa.MetodoIdentificacao.CPF)

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia_pergunta:
            m_pergunta = self._in(conv, "quanto pra quitar?")
            process_mensagem(m_pergunta.id)
        mock_ia_pergunta.assert_not_called()  # ainda dentro da janela de debounce

        # Envelhece em chamadas separadas (staggered) -- uma única chamada
        # bulk daria o MESMO `criado_em` às duas, deixando a ordem do lote
        # sujeita a empate.
        self._envelhecer(m_cpf, segundos=150)
        self._envelhecer(m_pergunta, segundos=140)

        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(saudacao=True)
            process_lote_conversa(conv.id)

        # 1 chamada de IA com o lote completo (as 2 mensagens, incluindo o
        # texto do CPF -- é a IA quem ignora, não o corte do lote).
        mock_ia.assert_called_once()
        args, kwargs = mock_ia.call_args
        self.assertEqual(args[0], ["529.982.247-25", "quanto pra quitar?"])
        # 1 conjunto de respostas -- não duas chamadas separadas.
        self.mock_client.send_text.assert_called_once()
        m_cpf.refresh_from_db()
        m_pergunta.refresh_from_db()
        self.assertIsNotNone(m_cpf.respondida_em)
        self.assertIsNotNone(m_pergunta.respondida_em)
