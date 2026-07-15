"""Testes do motor novo do bot (WS-D2).

Escopo: `whatsapp/tasks.py` (`process_mensagem` e o lock/coalescência),
`whatsapp/respostas_contrato.py` (renderer determinístico) e
`whatsapp/views.py` (`_extrair_conteudo` + webhook). `whatsapp.tasks.get_client`
e `whatsapp.tasks.extrair_intencao` são sempre mockados aqui -- nenhum teste
bate na Evolution API real nem no Gemini.
"""
import json
from datetime import timedelta
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
    Telefone,
)
from ia.schemas import (
    ClassificacaoMensagem,
    InfoContrato,
    InfoContratoPedido,
    SolicitacaoDraft,
    TipoIntencaoV2,
    TipoPagamento,
)
from whatsapp.respostas_contrato import (
    formatar_data,
    formatar_moeda,
    render_template,
    renderizar_infos_contrato,
)
from whatsapp.tasks import process_mensagem
from whatsapp.views import _extrair_conteudo


def _classificacao(tipo_intencao=TipoIntencaoV2.OUTRO, **kwargs):
    defaults = dict(
        tipo_intencao=tipo_intencao,
        faq_id=None,
        infos_contrato=[],
        solicitacoes=[],
        pronto_para_criar_solicitacao=False,
        precisa_humano=False,
        pergunta_sugerida_faq=None,
    )
    defaults.update(kwargs)
    return ClassificacaoMensagem(**defaults)


class WhatsappTasksTestCase(TestCase):
    """Base comum: bot ativo, database fresca, client Evolution mockado."""

    def setUp(self):
        self.bot = BotConfig.get_solo()
        self.bot.ativo = True
        self.bot.ultima_atualizacao_dados = timezone.now()
        self.bot.freshness_horas = 24
        self.bot.save()

        self.msgs = MensagensConfig.get_solo()

        self.mock_client = MagicMock()
        self.mock_client.send_text.return_value = True
        self.mock_client.send_file.return_value = True
        self.mock_client.mark_as_read.return_value = True

        patcher = patch("whatsapp.tasks.get_client", return_value=self.mock_client)
        self.mock_get_client = patcher.start()
        self.addCleanup(patcher.stop)

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
            TipoIntencaoV2.INFO_CONTRATO,
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
                TipoIntencaoV2.INFO_CONTRATO,
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
                TipoIntencaoV2.INFO_CONTRATO,
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
                TipoIntencaoV2.INFO_CONTRATO,
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
                TipoIntencaoV2.PAGAMENTO,
                solicitacoes=[SolicitacaoDraft(tipo=TipoPagamento.QUITAR, contratos=["C1"])],
                pronto_para_criar_solicitacao=True,
            )
            mensagem = self._in(conv, "quero quitar o contrato C1")
            process_mensagem(mensagem.id)

        self.assertEqual(self._last_out_texto(conv), self.msgs.msg_solicitacao_criada)
        self.assertNotEqual(self._last_out_texto(conv), self.msgs.msg_info_negada_desconhecido)


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
                TipoIntencaoV2.INFO_CONTRATO,
                infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            )
            mensagem = self._in(conv, "quando vence o C42?")
            process_mensagem(mensagem.id)

        texto = self._last_out_texto(conv)
        self.assertEqual(texto, esperado)
        self.assertIn(formatar_data(contrato.data_vencimento), texto)


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
            mock_ia.return_value = _classificacao(TipoIntencaoV2.DUVIDA_GERAL, faq_id=faq.id)
            mensagem = self._in(self.conv, "aceita relógio?")
            process_mensagem(mensagem.id)

        outs = list(
            self.conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).order_by("criado_em").values_list("texto", flat=True)
        )
        self.assertEqual(outs, ["oi", "Primeira resposta", "Segunda resposta"])

    def test_fallback_sem_resposta_cria_faq_sugerida_e_marca_revisao(self):
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(
                TipoIntencaoV2.DUVIDA_GERAL, pergunta_sugerida_faq="Vocês trabalham feriado?",
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
                TipoIntencaoV2.DUVIDA_GERAL, pergunta_sugerida_faq="Vocês trabalham feriado?",
            )
            m1 = self._in(self.conv, "vcs abrem no feriado?")
            process_mensagem(m1.id)
            m2 = self._in(self.conv, "e no feriado, funciona?")
            process_mensagem(m2.id)

        self.assertEqual(FAQSugerida.objects.filter(pergunta="Vocês trabalham feriado?").count(), 1)
        sugestao = FAQSugerida.objects.get(pergunta="Vocês trabalham feriado?")
        self.assertEqual(sugestao.ocorrencias, 2)


class FalsoPositivoCpfTests(WhatsappTasksTestCase):
    def setUp(self):
        super().setUp()
        self.conv = Conversa.objects.create(remote_jid="5567900000005@s.whatsapp.net")
        Mensagem.objects.create(conversa=self.conv, direcao=Mensagem.Direcao.OUT, texto="oi")

    def test_11_digitos_crus_fora_de_aguardando_verificacao_nao_dispara_cpf(self):
        self.conv.estado = Conversa.Estado.NOVA
        self.conv.save()
        with patch("whatsapp.tasks.extrair_intencao") as mock_ia:
            mock_ia.return_value = _classificacao(TipoIntencaoV2.SAUDACAO)
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
            mock_ia.return_value = _classificacao(TipoIntencaoV2.SAUDACAO)
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
            mock_ia.return_value = _classificacao(TipoIntencaoV2.SAUDACAO)
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
            mock_ia.return_value = _classificacao(TipoIntencaoV2.SAUDACAO)
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


class RenderizarInfosContratoTests(TestCase):
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
        self.assertEqual(resultado, self.msgs.msg_sem_contratos_ativos)

    def test_sem_contratos_ativos_retorna_mensagem_padrao(self):
        # cliente sem nenhum ContratoPenhor
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertEqual(resultado, self.msgs.msg_sem_contratos_ativos)

    def test_vencimento(self):
        c = self._contrato(contrato="C1")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertIn("C1", resultado)
        self.assertIn(formatar_data(c.data_vencimento), resultado)

    def test_renovacao_com_prazo_informado(self):
        self._contrato(contrato="C1", vlr_renovacao_60=1500)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=60)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        self.assertIn("R$ 1.500,00", resultado)
        self.assertIn("60", resultado)
        self.assertNotIn("prazo padrão", resultado)

    def test_renovacao_sem_prazo_usa_30_com_nota(self):
        self._contrato(contrato="C1", vlr_renovacao_30=1000)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        self.assertIn("R$ 1.000,00", resultado)
        self.assertIn("prazo padrão de 30 dias", resultado)

    def test_renovacao_prazo_45_mapeia_para_mais_proximo(self):
        # |45-30|=15 == |45-60|=15 -> empate resolvido pelo primeiro (30).
        self._contrato(contrato="C1", vlr_renovacao_30=999, vlr_renovacao_60=1999)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=45)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        self.assertIn("R$ 999,00", resultado)
        self.assertNotIn("R$ 1.999,00", resultado)

    def test_renovacao_prazo_100_mapeia_para_90(self):
        self._contrato(contrato="C1", vlr_renovacao_90=2500, vlr_renovacao_120=3000)
        pedido = InfoContratoPedido(info=InfoContrato.VALOR_RENOVACAO, prazo_dias=100)
        resultado = renderizar_infos_contrato(self.cliente, [pedido], self.msgs)
        self.assertIn("R$ 2.500,00", resultado)
        self.assertIn("90", resultado)

    def test_quitacao(self):
        self._contrato(contrato="C1", vlr_liquido=850)
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_QUITACAO)], self.msgs)
        self.assertIn("R$ 850,00", resultado)

    def test_parcela_pula_contrato_nao_parcelado(self):
        self._contrato(contrato="C1", parcelado=False, vlr_parcela=100)
        self._contrato(contrato="C2", parcelado=True, vlr_parcela=200)
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VALOR_PARCELA)], self.msgs)
        self.assertIn("C2", resultado)
        self.assertIn("R$ 200,00", resultado)
        self.assertNotIn("C1", resultado)
        self.assertNotIn("R$ 100,00", resultado)

    def test_multi_contrato_usa_header_e_footer(self):
        self._contrato(contrato="C1")
        self._contrato(contrato="C2")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertIn("C1", resultado)
        self.assertIn("C2", resultado)
        self.assertIn(render_template(self.msgs.tpl_lista_footer), resultado)

    def test_um_unico_contrato_nao_usa_header_footer(self):
        self._contrato(contrato="C1")
        resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=InfoContrato.VENCIMENTO)], self.msgs)
        self.assertNotIn(render_template(self.msgs.tpl_lista_footer), resultado)

    def test_lista_e_detalhe_usam_template_resumo(self):
        self._contrato(contrato="C1", vlr_emprestimo=500)
        for info in (InfoContrato.LISTA_CONTRATOS, InfoContrato.DETALHE_CONTRATO):
            resultado = renderizar_infos_contrato(self.cliente, [InfoContratoPedido(info=info)], self.msgs)
            self.assertIn("C1", resultado)
            self.assertIn("R$ 500,00", resultado)
