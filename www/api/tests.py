import json
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import (
    Boleto,
    BotConfig,
    Cliente,
    ContratoPenhor,
    Conversa,
    FAQ,
    FAQResposta,
    FAQSugerida,
    Mensagem,
    MensagensConfig,
    Solicitacao,
)
from ia.schemas import ClassificacaoLote, InfoContrato, InfoContratoPedido
from core.mensagens_defaults import MENSAGENS_DEFAULTS, SIMULADOR_SESSION_KEY


class APIEndpointsTestCase(APITestCase):
    def setUp(self):
        # Create users
        self.staff_user = User.objects.create_user(
            username="admin", password="password", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username="user", password="password", is_staff=False
        )

        # Create basic instances
        self.cliente = Cliente.objects.create(
            cpf="12345678901",
            nome="Cliente Teste",
            cidade="Campo Grande",
        )
        self.conversa = Conversa.objects.create(
            cliente=self.cliente,
            remote_jid="5567999999999@s.whatsapp.net",
            estado=Conversa.Estado.NOVA,
            tipo_contato=Conversa.TipoContato.CLIENTE,
            precisa_revisao_humana=False,
        )
        self.mensagem = Mensagem.objects.create(
            conversa=self.conversa,
            direcao=Mensagem.Direcao.IN,
            texto="Olá, gostaria de saber mais.",
            wa_message_id="msg_123",
        )
        self.contrato = ContratoPenhor.objects.create(
            contrato="12345",
            cliente=self.cliente,
            nome="Contrato Teste",
            situacao="Contrato em Aberto",
            situacao_codigo="EMNV",
            vlr_liquido=150.00,
            vlr_emprestimo=2000.00,
            data_vencimento=timezone.localdate() + timedelta(days=30),
        )
        self.solicitacao = Solicitacao.objects.create(
            cliente=self.cliente,
            conversa=self.conversa,
            tipo=Solicitacao.Tipo.QUITAR,
            status=Solicitacao.Status.PENDENTE,
        )
        self.solicitacao.contratos.add(self.contrato)

        self.faq = FAQ.objects.create(
            pergunta="Qual o horário de funcionamento?",
            ativo=True,
        )
        self.faq_resposta = FAQResposta.objects.create(
            faq=self.faq,
            ordem=0,
            texto="Funcionamos das 8h às 18h de segunda a sexta.",
        )

    # --- Permission Enforcement Tests ---

    def test_anonymous_user_forbidden(self):
        self.client.logout()
        self.client.force_authenticate(user=None)
        urls = [
            reverse("api:solicitacao-list"),
            reverse("api:dashboard-stats"),
            reverse("api:bot-config"),
            reverse("api:mensagens-config"),
            reverse("api:faq-list"),
            reverse("api:conversa-list"),
            reverse("api:cliente-list"),
            reverse("api:whatsapp-connection"),
            reverse("api:simulador"),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"URL {url} should be forbidden for anonymous user",
            )

    def test_regular_user_forbidden(self):
        self.client.logout()
        self.client.force_authenticate(user=self.regular_user)
        urls = [
            reverse("api:solicitacao-list"),
            reverse("api:dashboard-stats"),
            reverse("api:bot-config"),
            reverse("api:mensagens-config"),
            reverse("api:faq-list"),
            reverse("api:conversa-list"),
            reverse("api:cliente-list"),
            reverse("api:whatsapp-connection"),
            reverse("api:simulador"),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"URL {url} should be forbidden for regular user",
            )

    # --- Auth API Tests ---

    def test_auth_anonymous_get(self):
        url = reverse("api:auth")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["authenticated"])

    def test_auth_authenticated_get(self):
        url = reverse("api:auth")
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["authenticated"])
        self.assertEqual(response.data["username"], "admin")

    def test_auth_login_staff_success(self):
        url = reverse("api:auth")
        response = self.client.post(
            url,
            {"action": "login", "username": "admin", "password": "password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["authenticated"])
        self.assertEqual(response.data["username"], "admin")

    def test_auth_login_regular_forbidden(self):
        url = reverse("api:auth")
        response = self.client.post(
            url,
            {"action": "login", "username": "user", "password": "password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Acesso restrito", response.data["detail"])

    def test_auth_login_failed(self):
        url = reverse("api:auth")
        response = self.client.post(
            url,
            {"action": "login", "username": "admin", "password": "wrong_password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("incorretos", response.data["detail"])

    def test_auth_logout(self):
        url = reverse("api:auth")
        self.client.login(username="admin", password="password")
        response = self.client.post(url, {"action": "logout"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["authenticated"])

    def test_auth_invalid_action(self):
        url = reverse("api:auth")
        response = self.client.post(url, {"action": "invalid_action"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Solicitacoes API Tests ---

    def test_solicitacao_list(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:solicitacao-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.solicitacao.id)

    def test_solicitacao_list_filter(self):
        self.client.force_authenticate(user=self.staff_user)
        # Create another solicitacao with different status
        Solicitacao.objects.create(
            cliente=self.cliente,
            conversa=self.conversa,
            tipo=Solicitacao.Tipo.RENOVAR,
            status=Solicitacao.Status.CONCLUIDA,
        )
        url = reverse("api:solicitacao-list")
        
        response = self.client.get(url, {"status": "pendente"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["status"], "pendente")

        response = self.client.get(url, {"status": "concluida"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["status"], "concluida")

    def test_solicitacao_retrieve(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:solicitacao-detail", kwargs={"pk": self.solicitacao.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.solicitacao.id)
        self.assertEqual(response.data["cliente"]["cpf"], self.cliente.cpf)
        self.assertEqual(len(response.data["contratos"]), 1)
        self.assertEqual(response.data["contratos"][0]["contrato"], self.contrato.contrato)

    def test_solicitacao_partial_update(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:solicitacao-detail", kwargs={"pk": self.solicitacao.id})
        response = self.client.patch(url, {"status": "concluida"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.status, "concluida")

    @patch("api.views.async_task")
    def test_solicitacao_upload_boletos(self, mock_async_task):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:solicitacao-boletos", kwargs={"pk": self.solicitacao.id})
        
        pdf_file = SimpleUploadedFile("boleto1.pdf", b"pdf data 1", content_type="application/pdf")
        pdf_file2 = SimpleUploadedFile("boleto2.pdf", b"pdf data 2", content_type="application/pdf")
        
        payload = {
            "arquivo": [pdf_file, pdf_file2],
            "linha_digitavel": ["34191.79001 01043.513184 1", "34191.79001 01043.513184 2"]
        }
        response = self.client.post(url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Boleto.objects.filter(solicitacao=self.solicitacao).count(), 2)
        mock_async_task.assert_called_once_with("api.tasks.enviar_boletos", self.solicitacao.id)

    def test_solicitacao_upload_boletos_no_file(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:solicitacao-boletos", kwargs={"pk": self.solicitacao.id})
        response = self.client.post(url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Envie ao menos um PDF", response.data["detail"])

    # --- Dashboard API Tests ---

    def test_dashboard_stats(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:dashboard-stats")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("por_tipo", response.data)
        self.assertIn("por_status", response.data)
        self.assertIn("serie_30_dias", response.data)
        self.assertIn("total_clientes", response.data)
        self.assertIn("solicitacoes_precisa_humano", response.data)
        self.assertIn("buckets_dia_mes", response.data)

    # --- Configs API Tests ---

    def test_bot_config_get(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:bot-config")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["ativo"], False)
        self.assertEqual(response.data["freshness_horas"], 24)

    def test_bot_config_patch(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:bot-config")
        payload = {"ativo": True, "freshness_horas": 48}
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["ativo"], True)
        self.assertEqual(response.data["freshness_horas"], 48)

    def test_bot_config_patch_invalid(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:bot-config")
        payload = {"freshness_horas": "not-an-int"}
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("freshness_horas", response.data)

    def test_mensagens_config_get(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:mensagens-config")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("system_prompt", response.data)

    def test_mensagens_config_patch(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:mensagens-config")
        payload = {"msg_saudacao": "Nova Saudacao Personalizada"}
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["msg_saudacao"], "Nova Saudacao Personalizada")

    def test_mensagens_config_restore_success(self):
        self.client.force_authenticate(user=self.staff_user)
        # Edit it first
        config = MensagensConfig.get_solo()
        config.system_prompt = "Modified system prompt"
        config.save()

        url = reverse("api:mensagens-config")
        payload = {"campo": "system_prompt"}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["system_prompt"], MENSAGENS_DEFAULTS["system_prompt"])

    def test_mensagens_config_restore_invalid(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:mensagens-config")
        payload = {"campo": "campo_inexistente"}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Campo inválido", response.data["detail"])

    # --- FAQ CRUD API Tests ---

    def test_faq_list(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["pergunta"], self.faq.pergunta)

    def test_faq_create_json(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-list")
        payload = {
            "pergunta": "Como faço para renovar?",
            "ativo": True,
            "respostas": [
                {"ordem": 0, "texto": "Para renovar envie o contrato."},
                {"ordem": 1, "texto": "Ou use o site da Caixa."}
            ]
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FAQ.objects.filter(pergunta="Como faço para renovar?").count(), 1)
        new_faq = FAQ.objects.get(pergunta="Como faço para renovar?")
        self.assertEqual(new_faq.respostas.count(), 2)

    def test_faq_create_multipart(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-list")
        
        faq_data = {
            "pergunta": "Como amortizar?",
            "ativo": True,
            "respostas": [
                {"ordem": 0, "texto": "Envie o valor parcial."},
                {"ordem": 1, "texto": "Confira o comprovante."}
            ]
        }
        file_0 = SimpleUploadedFile("comprovante.png", b"fake png data", content_type="image/png")
        payload = {
            "faq": json.dumps(faq_data),
            "arquivo_0": file_0
        }
        response = self.client.post(url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        faq = FAQ.objects.get(pergunta="Como amortizar?")
        self.assertEqual(faq.respostas.count(), 2)
        respostas = faq.respostas.order_by("ordem")
        self.assertEqual(respostas[0].texto, "Envie o valor parcial.")
        self.assertIn("comprovante", respostas[0].arquivo.name)
        self.assertEqual(respostas[1].texto, "Confira o comprovante.")
        self.assertFalse(respostas[1].arquivo)

    def test_faq_update_multipart(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-detail", kwargs={"pk": self.faq.id})
        
        # Set an initial file for the first reply in the DB
        self.faq_resposta.arquivo = "faq_arquivos/antigo.pdf"
        self.faq_resposta.save()
        
        faq_data = {
            "pergunta": "Qual o horário de funcionamento? (Alterado)",
            "ativo": False,
            "respostas": [
                {"id": self.faq_resposta.id, "ordem": 0, "texto": "Novo texto 1", "arquivo": "/media/faq_arquivos/antigo.pdf"},
                {"ordem": 1, "texto": "Novo texto 2"}
            ]
        }
        file_1 = SimpleUploadedFile("anexo.pdf", b"pdf data", content_type="application/pdf")
        payload = {
            "faq": json.dumps(faq_data),
            "arquivo_1": file_1
        }
        response = self.client.put(url, payload, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.faq.refresh_from_db()
        self.assertEqual(self.faq.pergunta, "Qual o horário de funcionamento? (Alterado)")
        self.assertFalse(self.faq.ativo)
        
        respostas = self.faq.respostas.order_by("ordem")
        self.assertEqual(respostas.count(), 2)
        # Verify first reply preserved the file path
        self.assertEqual(respostas[0].arquivo.name, "faq_arquivos/antigo.pdf")
        # Verify second reply got the new uploaded file
        self.assertIn("anexo", respostas[1].arquivo.name)

    def test_faq_toggle(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-toggle", kwargs={"pk": self.faq.id})
        
        self.assertTrue(self.faq.ativo)
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["ativo"])
        
        self.faq.refresh_from_db()
        self.assertFalse(self.faq.ativo)

    def test_faq_delete(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-detail", kwargs={"pk": self.faq.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FAQ.objects.filter(id=self.faq.id).exists())

    # --- Conversas API Tests ---

    def test_conversa_list(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:conversa-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_conversa_list_filters(self):
        self.client.force_authenticate(user=self.staff_user)
        
        # Make first needs review
        self.conversa.precisa_revisao_humana = True
        self.conversa.save()
        
        # Create second
        Conversa.objects.create(
            remote_jid="5567888888888@s.whatsapp.net",
            estado=Conversa.Estado.ENCERRADA,
            tipo_contato=Conversa.TipoContato.PESSOAL,
            precisa_revisao_humana=False
        )
        url = reverse("api:conversa-list")
        
        # Filter: needs review
        response = self.client.get(url, {"revisao": "1"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.conversa.id)
        
        # Filter: estado
        response = self.client.get(url, {"estado": "encerrada"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["estado"], "encerrada")

        # Search: Q matches name or remote_jid or cpf
        response = self.client.get(url, {"q": "Teste"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.conversa.id)

    def test_conversa_retrieve(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:conversa-detail", kwargs={"pk": self.conversa.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.conversa.id)
        self.assertEqual(len(response.data["mensagens"]), 1)
        self.assertEqual(response.data["mensagens"][0]["texto"], "Olá, gostaria de saber mais.")
        self.assertEqual(len(response.data["solicitacoes"]), 1)

    def test_conversa_toggle_revisao(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:conversa-toggle-revisao", kwargs={"pk": self.conversa.id})
        
        self.assertFalse(self.conversa.precisa_revisao_humana)
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["precisa_revisao_humana"])
        
        self.conversa.refresh_from_db()
        self.assertTrue(self.conversa.precisa_revisao_humana)

    # --- Clientes API Tests ---

    def test_cliente_list(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:cliente-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_cliente_list_filters(self):
        self.client.force_authenticate(user=self.staff_user)
        
        # Create blocked client
        Cliente.objects.create(
            cpf="98765432109",
            nome="Spammer IA",
            cidade="Campo Grande",
            bloqueado_ia=True,
            bloqueado_motivo="Muitas mensagens"
        )
        url = reverse("api:cliente-list")
        
        # Filter: blocked only
        response = self.client.get(url, {"bloqueado": "1"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["cpf"], "98765432109")

        # Search: Q
        response = self.client.get(url, {"q": "Spammer"})
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["cpf"], "98765432109")

    def test_cliente_retrieve(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:cliente-detail", kwargs={"pk": self.cliente.cpf})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cpf"], self.cliente.cpf)
        self.assertEqual(len(response.data["contratos_penhor"]), 1)
        self.assertEqual(len(response.data["conversas"]), 1)
        self.assertEqual(len(response.data["solicitacoes"]), 1)

    def test_cliente_toggle_bloqueio(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:cliente-toggle-bloqueio", kwargs={"pk": self.cliente.cpf})
        
        # Block
        response = self.client.post(url, {"acao": "bloquear", "motivo": "Falar bobagem"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["bloqueado_ia"])
        self.assertEqual(response.data["bloqueado_motivo"], "Falar bobagem")
        
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.bloqueado_ia)
        self.assertEqual(self.cliente.bloqueado_motivo, "Falar bobagem")
        
        # Unblock
        response = self.client.post(url, {"acao": "desbloquear"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["bloqueado_ia"])
        self.assertEqual(response.data["bloqueado_motivo"], "")
        
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.bloqueado_ia)

    # --- WhatsApp connection mock tests ---

    @patch("api.views.get_client")
    def test_whatsapp_connection_get_open(self, mock_get_client):
        self.client.force_authenticate(user=self.staff_user)
        
        mock_evo = MagicMock()
        mock_evo.get_connection_state.return_value = "open"
        mock_get_client.return_value = mock_evo
        
        url = reverse("api:whatsapp-connection")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "open")
        self.assertEqual(response.data["bot_ativo"], False)
        self.assertNotIn("qrcode_base64", response.data)

    @patch("api.views.get_client")
    def test_whatsapp_connection_get_closed(self, mock_get_client):
        self.client.force_authenticate(user=self.staff_user)
        
        mock_evo = MagicMock()
        mock_evo.get_connection_state.return_value = "close"
        mock_evo.get_qrcode_base64.return_value = "data:image/png;base64,mockcode"
        mock_get_client.return_value = mock_evo
        
        url = reverse("api:whatsapp-connection")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"], "close")
        self.assertEqual(response.data["qrcode_base64"], "data:image/png;base64,mockcode")

    @patch("api.views.async_task")
    @patch("api.views.get_client")
    def test_whatsapp_connection_post(self, mock_get_client, mock_async_task):
        self.client.force_authenticate(user=self.staff_user)
        
        mock_evo = MagicMock()
        mock_evo.get_connection_state.return_value = "connecting"
        mock_evo.get_qrcode_base64.return_value = "data:image/png;base64,mockcode"
        mock_get_client.return_value = mock_evo
        
        url = reverse("api:whatsapp-connection")
        
        # Toggle bot configuration to active
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["bot_ativo"])
        self.assertEqual(response.data["state"], "connecting")
        self.assertEqual(response.data["qrcode_base64"], "data:image/png;base64,mockcode")

        self.assertEqual(mock_async_task.call_count, 2)
        mock_async_task.assert_any_call("whatsapp.tasks.sincronizar_contatos")
        mock_async_task.assert_any_call("whatsapp.tasks.processar_nao_lidas")

        # Toggle bot configuration back to inactive
        response = self.client.post(url)
        self.assertFalse(response.data["bot_ativo"])

    # --- Simulator API Tests ---

    @patch("api.views.extrair_intencao")
    def test_simulator_view_flow(self, mock_extrair_intencao):
        # Must login with django auth for session support
        self.client.login(username="admin", password="password")
        url = reverse("api:simulador")

        # GET initial
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["cliente"])
        self.assertEqual(response.data["turnos"], [])

        # Select client
        response = self.client.post(url, {"acao": "selecionar_cliente", "cpf": self.cliente.cpf}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cliente"]["cpf"], self.cliente.cpf)

        # Send simulated message. A partir do WS-A a IA é só classificadora
        # (nunca redige texto); o texto exibido vem do renderer determinístico
        # -- aqui, dúvida sem FAQ correspondente e sem outra ação cai no
        # fallback padrão.
        mock_result = ClassificacaoLote(
            saudacao=False,
            precisa_humano=False,
            solicitacoes=[],
            infos_contrato=[],
            pronto_para_criar_solicitacao=False,
            faq_ids=[],
            duvidas_sem_faq=["Aceita relógio?"],
        )
        mock_extrair_intencao.return_value = mock_result

        response = self.client.post(url, {"acao": "enviar", "mensagem": "Aceita relógio?"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["turnos"]), 2)
        self.assertEqual(response.data["turnos"][0]["texto"], "Aceita relógio?")
        self.assertEqual(response.data["turnos"][1]["texto"], MensagensConfig.get_solo().msg_fallback_sem_resposta)
        self.assertEqual(response.data["turnos"][1]["debug"]["acoes"], ["duvida_sem_faq:1"])

        # Restart
        response = self.client.post(url, {"acao": "reiniciar"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["turnos"], [])

        # Remove client
        response = self.client.post(url, {"acao": "remover_cliente"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["cliente"])

    @patch("api.views.extrair_intencao")
    def test_simulator_view_flow_appenda_um_turno_out_por_mensagem(self, mock_extrair_intencao):
        # info_contrato com 2+ contratos ativos faz fan-out: intro + 1 linha
        # por contrato + totalizador -- cada um deve virar 1 turno "out"
        # separado (paridade com o WhatsApp real via `_enviar_fila`); o
        # `debug` só aparece no último turno.
        ContratoPenhor.objects.create(
            contrato="67890",
            cliente=self.cliente,
            nome="Segundo Contrato",
            situacao="Contrato em Aberto",
            situacao_codigo="EMNV",
            vlr_emprestimo=1000.00,
            data_vencimento=timezone.localdate() + timedelta(days=45),
        )

        self.client.login(username="admin", password="password")
        url = reverse("api:simulador")

        response = self.client.post(url, {"acao": "selecionar_cliente", "cpf": self.cliente.cpf}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_extrair_intencao.return_value = ClassificacaoLote(
            saudacao=False,
            precisa_humano=False,
            solicitacoes=[],
            infos_contrato=[InfoContratoPedido(info=InfoContrato.VENCIMENTO)],
            pronto_para_criar_solicitacao=False,
            faq_ids=[],
            duvidas_sem_faq=[],
        )

        response = self.client.post(url, {"acao": "enviar", "mensagem": "quando vencem meus contratos?"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        turnos = response.data["turnos"]

        # 1 turno "in" + (intro + 2 linhas + totalizador) turnos "out" = 5
        self.assertEqual(len(turnos), 5)
        self.assertEqual(turnos[0]["direcao"], "in")
        turnos_out = turnos[1:]
        for turno in turnos_out[:-1]:
            self.assertNotIn("debug", turno)
        self.assertIn("debug", turnos_out[-1])
        self.assertEqual(turnos_out[-1]["debug"]["acoes"], ["info_contrato:1"])


# --- WS-D2: mídia no detail de conversa, envio de arquivo, FAQs sugeridas ----


class ConversaDetailMidiaTestCase(APITestCase):
    """`ConversaDetailSerializer.get_mensagens` usa `MensagemPainelSerializer`
    (WS-B): precisa expor os campos de mídia/envio que o frontend consome e
    NUNCA `payload_bruto` (não deve vazar o payload bruto da Evolution)."""

    def setUp(self):
        self.staff_user = User.objects.create_user(username="admin2", password="password", is_staff=True)
        self.conversa = Conversa.objects.create(
            remote_jid="5567988776655@s.whatsapp.net",
            estado=Conversa.Estado.NOVA,
            tipo_contato=Conversa.TipoContato.DESCONHECIDO,
        )
        self.mensagem_midia = Mensagem.objects.create(
            conversa=self.conversa,
            direcao=Mensagem.Direcao.IN,
            texto="",
            tipo_midia=Mensagem.TipoMidia.IMAGE,
            payload_bruto={"segredo_evolution": "nao_deve_vazar_para_o_frontend"},
        )

    def test_detail_expoe_campos_de_midia_e_envio(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:conversa-detail", kwargs={"pk": self.conversa.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mensagens = response.data["mensagens"]
        self.assertEqual(len(mensagens), 1)
        msg_data = mensagens[0]
        for campo in ("possui_midia", "tipo_midia", "enviado_ok", "arquivo"):
            self.assertIn(campo, msg_data)
        self.assertTrue(msg_data["possui_midia"])
        self.assertEqual(msg_data["tipo_midia"], "image")
        self.assertNotIn("payload_bruto", msg_data)
        self.assertNotIn("segredo_evolution", json.dumps(msg_data))


class BaixarMediaMensagemTestCase(APITestCase):
    """Regressão: `baixar_media_mensagem` usava `settings.EVOLUTION_API_URL`
    sem importar `settings` -- NameError em produção (500) toda vez que o
    operador tentava abrir uma imagem/áudio recebido, sem nenhum teste
    cobrindo o caminho feliz até a chamada à Evolution API."""

    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffmedia", password="password", is_staff=True)
        self.conversa = Conversa.objects.create(
            remote_jid="5567988776655@s.whatsapp.net",
            estado=Conversa.Estado.NOVA,
            tipo_contato=Conversa.TipoContato.DESCONHECIDO,
        )
        self.mensagem = Mensagem.objects.create(
            conversa=self.conversa,
            direcao=Mensagem.Direcao.IN,
            texto="",
            tipo_midia=Mensagem.TipoMidia.IMAGE,
            payload_bruto={
                "data": {
                    "key": {"id": "WA123"},
                    "message": {"imageMessage": {"mimetype": "image/jpeg"}},
                }
            },
        )

    def _url(self):
        return f"/api/conversas/{self.conversa.id}/mensagens/{self.mensagem.id}/media/"

    @patch("requests.post")
    def test_baixa_midia_com_sucesso(self, mock_post):
        import base64
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"base64": base64.b64encode(b"fake-jpeg-bytes").decode(), "mimetype": "image/jpeg"},
        )
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"fake-jpeg-bytes")
        self.assertEqual(response["Content-Type"], "image/jpeg")

    @patch("requests.post")
    def test_erro_da_evolution_api_retorna_502_sem_quebrar(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500)
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_mensagem_sem_midia_retorna_404(self):
        mensagem_texto = Mensagem.objects.create(
            conversa=self.conversa,
            direcao=Mensagem.Direcao.IN,
            texto="oi",
            payload_bruto={"data": {"message": {"conversation": "oi"}}},
        )
        self.client.force_authenticate(user=self.staff_user)
        url = f"/api/conversas/{self.conversa.id}/mensagens/{mensagem_texto.id}/media/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("requests.post")
    def test_midia_embrulhada_em_ephemeral_message_e_baixada(self, mock_post):
        import base64
        mensagem_efemera = Mensagem.objects.create(
            conversa=self.conversa,
            direcao=Mensagem.Direcao.IN,
            texto="",
            tipo_midia=Mensagem.TipoMidia.AUDIO,
            payload_bruto={
                "data": {
                    "key": {"id": "WA124"},
                    "message": {"ephemeralMessage": {"message": {"audioMessage": {"mimetype": "audio/ogg"}}}},
                }
            },
        )
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"base64": base64.b64encode(b"fake-audio-bytes").decode(), "mimetype": "audio/ogg"},
        )
        self.client.force_authenticate(user=self.staff_user)
        url = f"/api/conversas/{self.conversa.id}/mensagens/{mensagem_efemera.id}/media/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"fake-audio-bytes")


class ConversaEnviarArquivoTestCase(APITestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffarq", password="password", is_staff=True)
        self.regular_user = User.objects.create_user(username="userarq", password="password", is_staff=False)
        self.conversa = Conversa.objects.create(
            remote_jid="5567999999999@s.whatsapp.net",
            estado=Conversa.Estado.NOVA,
            tipo_contato=Conversa.TipoContato.CLIENTE,
        )
        self.url = reverse("api:conversa-enviar-arquivo", kwargs={"pk": self.conversa.id})

    @patch("api.views.get_client")
    def test_enviar_arquivo_sucesso(self, mock_get_client):
        self.client.force_authenticate(user=self.staff_user)
        mock_evo = MagicMock()
        mock_evo.send_file.return_value = True
        mock_get_client.return_value = mock_evo

        arquivo = SimpleUploadedFile("foto.jpg", b"fake jpg bytes", content_type="image/jpeg")
        response = self.client.post(
            self.url, {"arquivo": arquivo, "legenda": "segue a foto"}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["tipo_midia"], "image")
        self.assertEqual(response.data["enviado_ok"], True)
        mock_evo.send_file.assert_called_once()

        mensagem = Mensagem.objects.get(conversa=self.conversa, direcao=Mensagem.Direcao.OUT)
        self.assertEqual(mensagem.tipo_midia, Mensagem.TipoMidia.IMAGE)
        self.assertTrue(mensagem.enviado_ok)
        self.assertEqual(mensagem.texto, "segue a foto")

    def test_enviar_arquivo_extensao_proibida(self):
        self.client.force_authenticate(user=self.staff_user)
        arquivo = SimpleUploadedFile("virus.exe", b"binario qualquer", content_type="application/octet-stream")
        response = self.client.post(self.url, {"arquivo": arquivo}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Mensagem.objects.filter(conversa=self.conversa).count(), 0)

    def test_enviar_arquivo_excede_tamanho_maximo(self):
        self.client.force_authenticate(user=self.staff_user)
        from api.views import ConversaViewSet

        with patch.object(ConversaViewSet, "_TAMANHO_MAXIMO_ANEXO_BYTES", 10):
            arquivo = SimpleUploadedFile("foto.jpg", b"mais de dez bytes de conteudo", content_type="image/jpeg")
            response = self.client.post(self.url, {"arquivo": arquivo}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("tamanho", response.data["detail"].lower())

    def test_enviar_arquivo_sem_arquivo(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post(self.url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_enviar_arquivo_nao_staff_forbidden(self):
        self.client.force_authenticate(user=self.regular_user)
        arquivo = SimpleUploadedFile("foto.jpg", b"fake jpg bytes", content_type="image/jpeg")
        response = self.client.post(self.url, {"arquivo": arquivo}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FAQSugeridaViewSetTestCase(APITestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffsug", password="password", is_staff=True)
        self.regular_user = User.objects.create_user(username="usersug", password="password", is_staff=False)
        self.pendente = FAQSugerida.objects.create(
            pergunta="Vocês trabalham no feriado?",
            pergunta_original="vcs abrem no feriado?",
            ocorrencias=3,
        )
        self.aprovada = FAQSugerida.objects.create(
            pergunta="Já aprovada antes",
            status=FAQSugerida.Status.APROVADA,
        )

    def test_list_todas(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(reverse("api:faq-sugerida-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_filtro_status(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(reverse("api:faq-sugerida-list"), {"status": "pendente"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.pendente.id)

    def test_aprovar_cria_faq_com_respostas_e_marca_aprovada(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-sugerida-aprovar", kwargs={"pk": self.pendente.id})
        payload = {
            "pergunta_final": "Vocês atendem em feriados?",
            "respostas": [
                {"ordem": 0, "texto": "Sim, em horário reduzido."},
                {"ordem": 1, "texto": "Confira o quadro de horários no local."},
            ],
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.pendente.refresh_from_db()
        self.assertEqual(self.pendente.status, FAQSugerida.Status.APROVADA)
        self.assertEqual(self.pendente.revisado_por, self.staff_user)
        self.assertIsNotNone(self.pendente.revisado_em)
        self.assertIsNotNone(self.pendente.faq_criada)

        faq = self.pendente.faq_criada
        self.assertEqual(faq.pergunta, "Vocês atendem em feriados?")
        self.assertTrue(faq.ativo)
        self.assertEqual(faq.respostas.count(), 2)

    def test_aprovar_sem_pergunta_final_usa_pergunta_da_sugestao(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-sugerida-aprovar", kwargs={"pk": self.pendente.id})
        response = self.client.post(url, {"respostas": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.pendente.refresh_from_db()
        self.assertEqual(self.pendente.faq_criada.pergunta, self.pendente.pergunta)

    def test_rejeitar(self):
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("api:faq-sugerida-rejeitar", kwargs={"pk": self.pendente.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.pendente.refresh_from_db()
        self.assertEqual(self.pendente.status, FAQSugerida.Status.REJEITADA)
        self.assertEqual(self.pendente.revisado_por, self.staff_user)
        self.assertIsNotNone(self.pendente.revisado_em)
        self.assertIsNone(self.pendente.faq_criada)

    def test_permissoes_nao_staff_forbidden(self):
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(reverse("api:faq-sugerida-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        url = reverse("api:faq-sugerida-aprovar", kwargs={"pk": self.pendente.id})
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_permissoes_anonimo_forbidden(self):
        response = self.client.get(reverse("api:faq-sugerida-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class DashboardFaqsSugeridasPendentesTestCase(APITestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username="staffdash", password="password", is_staff=True)
        FAQSugerida.objects.create(pergunta="Pendente 1")
        FAQSugerida.objects.create(pergunta="Pendente 2")
        FAQSugerida.objects.create(pergunta="Já tratada", status=FAQSugerida.Status.REJEITADA)

    def test_dashboard_retorna_contagem_de_pendentes(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get(reverse("api:dashboard-stats"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["faqs_sugeridas_pendentes"], 2)
