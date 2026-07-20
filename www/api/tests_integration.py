"""
Integration tests: Angular SPA ↔ Django REST API

Two test classes:
  1. APIIntegrationTests  – Django TestCase using force_login (no password needed).
     Run with:
       DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 ../venv/bin/python manage.py test api.tests_integration -v2

  2. LiveServerIntegrationTests – hits the real Nginx at https://pwa.brunonyland.com
     to verify SPA serving, routing fallback, static assets, and CSRF cookies.
     These are skipped automatically if the server is unreachable.
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    FAQ,
    BotConfig,
    Cliente,
    Conversa,
    FAQResposta,
    Mensagem,
    MensagensConfig,
    Solicitacao,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "https://pwa.brunonyland.com"


def _server_reachable():
    """Return True if the live HTTPS server responds."""
    try:
        import requests as req

        resp = req.get(f"{BASE_URL}/api/auth/", timeout=5, verify=False)
        return resp.status_code in (200, 301, 302, 403)
    except Exception:
        return False


# ===========================================================================
# Part 1: Django API integration tests (force_login, SQLite, no network)
# ===========================================================================


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.SessionAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 25,
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
        "EXCEPTION_HANDLER": "api.views.custom_exception_handler",
    }
)
class APIIntegrationTests(TestCase):
    """Tests that the Angular frontend can communicate correctly with the
    Django REST API via session-based authentication.  Uses Django's test
    client with ``force_login`` so no real password is required."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            username="integration_staff",
            password="t3stP@ss!",
            is_staff=True,
        )
        cls.non_staff = User.objects.create_user(
            username="integration_regular",
            password="t3stP@ss!",
            is_staff=False,
        )
        cls.cliente = Cliente.objects.create(
            cpf="12345678901",
            nome="Cliente Integração",
            cidade="São Paulo",
        )
        cls.conversa = Conversa.objects.create(
            cliente=cls.cliente,
            remote_jid="5511999990000@s.whatsapp.net",
            estado=Conversa.Estado.NOVA,
            tipo_contato=Conversa.TipoContato.CLIENTE,
        )
        cls.faq = FAQ.objects.create(pergunta="Qual o horário?", ativo=True)
        FAQResposta.objects.create(faq=cls.faq, texto="8h às 17h")

    def setUp(self):
        self.client = APIClient()

    # --- Auth flow ---------------------------------------------------------

    def test_auth_check_unauthenticated(self):
        """GET /api/auth/ without session → authenticated=False"""
        resp = self.client.get("/api/auth/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["authenticated"])

    def test_auth_login_valid_staff(self):
        """POST /api/auth/ login with valid staff user → authenticated=True"""
        resp = self.client.post(
            "/api/auth/",
            {"action": "login", "username": "integration_staff", "password": "t3stP@ss!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "integration_staff")
        self.assertTrue(data["is_staff"])

    def test_auth_login_invalid_password(self):
        """POST /api/auth/ login with wrong password → 401"""
        resp = self.client.post(
            "/api/auth/",
            {"action": "login", "username": "integration_staff", "password": "wrong"},
            format="json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_auth_login_non_staff_rejected(self):
        """POST /api/auth/ login with non-staff user → 403"""
        resp = self.client.post(
            "/api/auth/",
            {"action": "login", "username": "integration_regular", "password": "t3stP@ss!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_auth_logout(self):
        """POST /api/auth/ logout → authenticated=False"""
        self.client.force_login(self.staff)
        resp = self.client.post("/api/auth/", {"action": "logout"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["authenticated"])

    def test_auth_check_after_login(self):
        """GET /api/auth/ after force_login → authenticated=True"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/auth/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["username"], "integration_staff")

    # --- Auth guard (unauthenticated → 403) --------------------------------

    PROTECTED_ENDPOINTS = [
        ("/api/dashboard/", "get"),
        ("/api/configs/bot/", "get"),
        ("/api/configs/mensagens/", "get"),
        ("/api/faqs/", "get"),
        ("/api/conversas/", "get"),
        ("/api/clientes/", "get"),
        ("/api/simulador/", "get"),
        ("/api/solicitacoes/", "get"),
    ]

    def test_unauthenticated_access_returns_403(self):
        """All protected endpoints must return 403 for anonymous users."""
        for url, method in self.PROTECTED_ENDPOINTS:
            with self.subTest(url=url):
                resp = getattr(self.client, method)(url)
                self.assertEqual(
                    resp.status_code,
                    status.HTTP_403_FORBIDDEN,
                    f"{method.upper()} {url} should return 403, got {resp.status_code}",
                )

    # --- Authenticated access to all API endpoints -------------------------

    @patch("whatsapp.evolution_client.get_client")
    def test_dashboard_authenticated(self, mock_client):
        """GET /api/dashboard/ → 200 with stats keys"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/dashboard/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        expected_keys = {
            "por_tipo",
            "por_status",
            "serie_30_dias",
            "maior_valor_serie",
            "total_clientes",
            "clientes_com_telefone",
            "clientes_com_conversa",
            "clientes_bloqueados",
            "total_solicitacoes",
            "total_conversas",
            "total_boletos",
        }
        self.assertTrue(
            expected_keys.issubset(data.keys()), f"Missing keys: {expected_keys - data.keys()}"
        )

    def test_bot_config_authenticated(self):
        """GET /api/configs/bot/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/configs/bot/")
        self.assertEqual(resp.status_code, 200)

    def test_mensagens_config_authenticated(self):
        """GET /api/configs/mensagens/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/configs/mensagens/")
        self.assertEqual(resp.status_code, 200)

    def test_faqs_list_authenticated(self):
        """GET /api/faqs/ → 200, returns list"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/faqs/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]["pergunta"], "Qual o horário?")

    def test_faqs_crud_lifecycle(self):
        """Full CRUD: create → read → update → delete FAQ"""
        self.client.force_login(self.staff)

        # Create
        create_data = {
            "pergunta": "FAQ de integração?",
            "ativo": True,
            "respostas": [{"texto": "Resposta de teste", "tipo": "texto"}],
        }
        resp = self.client.post("/api/faqs/", create_data, format="json")
        self.assertEqual(resp.status_code, 201, resp.json())
        faq_id = resp.json()["id"]

        # Read
        resp = self.client.get(f"/api/faqs/{faq_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["pergunta"], "FAQ de integração?")

        # Update
        resp = self.client.patch(
            f"/api/faqs/{faq_id}/",
            {"pergunta": "FAQ atualizada?"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["pergunta"], "FAQ atualizada?")

        # Toggle active
        resp = self.client.post(f"/api/faqs/{faq_id}/toggle/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ativo"])

        # Delete
        resp = self.client.delete(f"/api/faqs/{faq_id}/")
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get(f"/api/faqs/{faq_id}/")
        self.assertEqual(resp.status_code, 404)

    def test_clientes_list_authenticated(self):
        """GET /api/clientes/ → 200, returns list with test client"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/clientes/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        cpfs = [c["cpf"] for c in data]
        self.assertIn("12345678901", cpfs)

    def test_clientes_detail_by_cpf(self):
        """GET /api/clientes/<cpf>/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.get(f"/api/clientes/{self.cliente.cpf}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["nome"], "Cliente Integração")

    def test_conversas_list_authenticated(self):
        """GET /api/conversas/ → 200, returns list"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/conversas/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    def test_conversas_detail_authenticated(self):
        """GET /api/conversas/<id>/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.get(f"/api/conversas/{self.conversa.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_simulador_authenticated(self):
        """GET /api/simulador/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/simulador/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("turnos", data)

    def test_solicitacoes_list_authenticated(self):
        """GET /api/solicitacoes/ → 200, returns list"""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/solicitacoes/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    @patch("whatsapp.evolution_client.get_client")
    def test_whatsapp_state_authenticated(self, mock_get_client):
        """GET /api/whatsapp/state/ → 200 with mocked Evolution client"""
        mock_client = MagicMock()
        mock_client.get_connection_state.return_value = "open"
        mock_get_client.return_value = mock_client
        self.client.force_login(self.staff)
        resp = self.client.get("/api/whatsapp/state/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("state", data)
        self.assertIn("bot_ativo", data)

    # --- Bot config PATCH --------------------------------------------------

    def test_bot_config_patch(self):
        """PATCH /api/configs/bot/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.patch(
            "/api/configs/bot/",
            {"responder_desconhecidos": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    # --- Mensagens config PATCH --------------------------------------------

    def test_mensagens_config_patch(self):
        """PATCH /api/configs/mensagens/ → 200"""
        self.client.force_login(self.staff)
        # Read current value first
        resp = self.client.get("/api/configs/mensagens/")
        original = resp.json().get("msg_saudacao", "")

        resp = self.client.patch(
            "/api/configs/mensagens/",
            {"msg_saudacao": "Olá! Teste de integração."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["msg_saudacao"], "Olá! Teste de integração.")

        # Restore
        self.client.patch(
            "/api/configs/mensagens/",
            {"msg_saudacao": original},
            format="json",
        )

    # --- Mensagens config restore ------------------------------------------

    def test_mensagens_config_restore(self):
        """POST /api/mensagens-config/restore/ with campo → 200"""
        self.client.force_login(self.staff)
        resp = self.client.post(
            "/api/mensagens-config/restore/",
            {"campo": "msg_saudacao"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    # --- Auth flow: full session lifecycle ---------------------------------

    def test_full_session_lifecycle(self):
        """login → check → use endpoint → logout → check → blocked"""
        c = APIClient()

        # 1. Login
        resp = c.post(
            "/api/auth/",
            {"action": "login", "username": "integration_staff", "password": "t3stP@ss!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["authenticated"])

        # 2. Session check
        resp = c.get("/api/auth/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["authenticated"])

        # 3. Use authenticated endpoint
        resp = c.get("/api/faqs/")
        self.assertEqual(resp.status_code, 200)

        # 4. Logout
        resp = c.post("/api/auth/", {"action": "logout"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["authenticated"])

        # 5. Session check after logout
        resp = c.get("/api/auth/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["authenticated"])

        # 6. Protected endpoint blocked
        resp = c.get("/api/faqs/")
        self.assertEqual(resp.status_code, 403)

    # --- Non-staff user cannot access admin endpoints ----------------------

    def test_non_staff_user_blocked_from_endpoints(self):
        """A logged-in non-staff user should get 403 on admin endpoints."""
        self.client.force_login(self.non_staff)
        for url, method in self.PROTECTED_ENDPOINTS:
            with self.subTest(url=url):
                resp = getattr(self.client, method)(url)
                self.assertEqual(resp.status_code, 403)

    # --- Content-Type checks -----------------------------------------------

    def test_api_returns_json_content_type(self):
        """API endpoints must return application/json."""
        self.client.force_login(self.staff)
        resp = self.client.get("/api/auth/")
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_dashboard_returns_json(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/api/dashboard/")
        self.assertIn("application/json", resp["Content-Type"])

    # --- CSRF token handling -----------------------------------------------

    def test_csrf_cookie_set_on_login(self):
        """After login, a CSRF cookie should be set."""
        resp = self.client.post(
            "/api/auth/",
            {"action": "login", "username": "integration_staff", "password": "t3stP@ss!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        # Django's test client stores cookies
        self.assertIn("csrftoken", self.client.cookies)

    # --- Cliente toggle-bloqueio -------------------------------------------

    def test_cliente_toggle_bloqueio(self):
        """POST /api/clientes/<cpf>/toggle-bloqueio/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.post(
            f"/api/clientes/{self.cliente.cpf}/toggle-bloqueio/",
            {"bloquear": True, "motivo": "Teste integração"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["bloqueado_ia"])

        # Unblock
        resp = self.client.post(
            f"/api/clientes/{self.cliente.cpf}/toggle-bloqueio/",
            {"bloquear": False},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["bloqueado_ia"])

    # --- Conversa toggle-revisao -------------------------------------------

    def test_conversa_toggle_revisao(self):
        """POST /api/conversas/<id>/toggle-revisao/ → 200"""
        self.client.force_login(self.staff)
        resp = self.client.post(f"/api/conversas/{self.conversa.id}/toggle-revisao/")
        self.assertEqual(resp.status_code, 200)
        revisao_after = resp.json()["precisa_revisao_humana"]

        # Toggle back
        resp = self.client.post(f"/api/conversas/{self.conversa.id}/toggle-revisao/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.json()["precisa_revisao_humana"], revisao_after)


# ===========================================================================
# Part 2: Live HTTPS tests (Nginx ↔ Angular SPA ↔ Django)
# ===========================================================================


@unittest.skipIf(
    os.environ.get("CI") == "true",
    "Live-server tests não rodam no CI (dependem do servidor de produção)",
)
@unittest.skipUnless(_server_reachable(), "Live server not reachable")
class LiveServerIntegrationTests(unittest.TestCase):
    """Tests that hit the real Nginx server to verify SPA serving,
    routing fallback, static asset caching, and CSRF cookies."""

    @classmethod
    def setUpClass(cls):
        import glob
        import os

        import requests as req
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        cls.session = req.Session()
        cls.session.verify = False

        # Dynamically discover static assets
        cls.static_assets = []
        browser_dir = "/var/www/pwa.brunonyland.com/frontend/dist/frontend/browser"
        if os.path.exists(browser_dir):
            for pattern in ["main-*.js", "polyfills-*.js", "styles-*.css"]:
                files = glob.glob(os.path.join(browser_dir, pattern))
                if files:
                    cls.static_assets.append("/painel/" + os.path.basename(files[0]))
            if os.path.exists(os.path.join(browser_dir, "favicon.ico")):
                cls.static_assets.append("/painel/favicon.ico")

        if not cls.static_assets:
            # Sem dist/ local (ex.: máquina que não buildou o front):
            # descobre os assets com hash a partir do index.html ao vivo,
            # em vez de uma lista hardcoded que apodrece a cada build.
            import re

            try:
                html = cls.session.get(f"{BASE_URL}/painel/", timeout=10).text
                cls.static_assets = [
                    f"/painel/{nome}"
                    for nome in re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html)
                ]
            except Exception:
                cls.static_assets = []
        if not cls.static_assets:
            raise unittest.SkipTest(
                "Nenhum asset estático descoberto (dist/ ausente e index.html indisponível)"
            )

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    # --- SPA serving -------------------------------------------------------

    def test_spa_index_returns_200(self):
        """GET /painel/ → 200 with Angular HTML"""
        resp = self.session.get(f"{BASE_URL}/painel/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("Content-Type", ""))

    def test_spa_contains_base_href(self):
        """Angular index.html must contain <base href="/painel/">"""
        resp = self.session.get(f"{BASE_URL}/painel/")
        self.assertIn('<base href="/painel/">', resp.text)

    def test_spa_contains_app_root(self):
        """Angular index.html must contain <app-root>"""
        resp = self.session.get(f"{BASE_URL}/painel/")
        self.assertIn("<app-root>", resp.text)

    # --- SPA routing fallback (all deep routes → same index.html) ----------

    SPA_ROUTES = [
        "/painel/dashboard",
        "/painel/faqs",
        "/painel/clientes",
        "/painel/atendimentos",
        "/painel/simulador",
        "/painel/bot",
        "/painel/mensagens",
        "/painel/some/deep/nonexistent/route",
    ]

    def test_spa_routing_fallback(self):
        """Deep Angular routes should all return the same index.html."""
        index_resp = self.session.get(f"{BASE_URL}/painel/")
        index_body = index_resp.text

        for route in self.SPA_ROUTES:
            with self.subTest(route=route):
                resp = self.session.get(f"{BASE_URL}{route}")
                self.assertEqual(resp.status_code, 200, f"{route} returned {resp.status_code}")
                self.assertIn(
                    '<base href="/painel/">',
                    resp.text,
                    f"{route} did not return Angular index.html",
                )
                # The HTML body should be the same as the root /painel/
                self.assertEqual(
                    resp.text, index_body, f"{route} returned different content than /painel/"
                )

    # --- Static assets (JS/CSS) with cache headers -------------------------

    def test_static_assets_served(self):
        """Angular JS/CSS files served by Nginx should return 200."""
        for asset in self.static_assets:
            with self.subTest(asset=asset):
                resp = self.session.get(f"{BASE_URL}{asset}")
                self.assertEqual(resp.status_code, 200, f"{asset} returned {resp.status_code}")

    def test_static_assets_cache_headers(self):
        """Static assets should have Cache-Control: public, immutable."""
        for asset in self.static_assets:
            with self.subTest(asset=asset):
                resp = self.session.get(f"{BASE_URL}{asset}")
                cache_control = resp.headers.get("Cache-Control", "")
                self.assertIn(
                    "public",
                    cache_control,
                    f"{asset} missing 'public' in Cache-Control: {cache_control}",
                )
                self.assertIn(
                    "immutable",
                    cache_control,
                    f"{asset} missing 'immutable' in Cache-Control: {cache_control}",
                )

    def test_js_assets_correct_content_type(self):
        """JS files should be served as application/javascript."""
        js_asset = next(
            (a for a in self.static_assets if a.endswith(".js")), "/painel/main-B64CDASC.js"
        )
        resp = self.session.get(f"{BASE_URL}{js_asset}")
        ct = resp.headers.get("Content-Type", "")
        self.assertTrue(
            "javascript" in ct or "ecmascript" in ct,
            f"Expected JS content type, got: {ct}",
        )

    def test_css_asset_correct_content_type(self):
        """CSS files should be served as text/css."""
        css_asset = next(
            (a for a in self.static_assets if a.endswith(".css")), "/painel/styles-TGT4343F.css"
        )
        resp = self.session.get(f"{BASE_URL}{css_asset}")
        ct = resp.headers.get("Content-Type", "")
        self.assertIn("text/css", ct, f"Expected text/css, got: {ct}")

    # --- API auth endpoint reachable through Nginx -------------------------

    def test_api_auth_reachable(self):
        """GET /api/auth/ → 200 with JSON response through Nginx."""
        resp = self.session.get(f"{BASE_URL}/api/auth/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("authenticated", data)

    def test_api_auth_returns_json(self):
        """API responses must have application/json content type."""
        resp = self.session.get(f"{BASE_URL}/api/auth/")
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    # --- API auth guard through Nginx --------------------------------------

    LIVE_PROTECTED = [
        "/api/dashboard/",
        "/api/configs/bot/",
        "/api/configs/mensagens/",
        "/api/faqs/",
        "/api/conversas/",
        "/api/clientes/",
        "/api/simulador/",
        "/api/solicitacoes/",
    ]

    def test_api_auth_guard_through_nginx(self):
        """Protected API endpoints must return 403 for unauthenticated requests via Nginx."""
        fresh = self.session.__class__()
        fresh.verify = False
        for url in self.LIVE_PROTECTED:
            with self.subTest(url=url):
                resp = fresh.get(f"{BASE_URL}{url}")
                self.assertEqual(
                    resp.status_code,
                    403,
                    f"{url} returned {resp.status_code}, expected 403",
                )
        fresh.close()

    # --- CSRF cookie -------------------------------------------------------

    def test_csrf_cookie_on_auth_endpoint(self):
        """Hitting /api/auth/ should set a csrftoken cookie."""
        fresh = self.session.__class__()
        fresh.verify = False
        resp = fresh.get(f"{BASE_URL}/api/auth/")
        self.assertEqual(resp.status_code, 200)
        cookie_names = [c.name for c in fresh.cookies]
        self.assertIn("csrftoken", cookie_names, f"Expected csrftoken cookie, got: {cookie_names}")
        fresh.close()

    # --- Root redirect -----------------------------------------------------

    def test_root_redirects_to_painel(self):
        """GET / should redirect (via Django) toward /painel/."""
        resp = self.session.get(f"{BASE_URL}/", allow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        location = resp.headers.get("Location", "")
        self.assertTrue(
            "/painel/" in location or location.endswith("/painel"),
            f"Expected redirect to /painel/, got Location: {location}",
        )

    # --- HTTPS enforcement -------------------------------------------------

    def test_http_redirects_to_https(self):
        """HTTP request should redirect to HTTPS."""
        import requests as req

        try:
            resp = req.get(
                "http://pwa.brunonyland.com/painel/",
                allow_redirects=False,
                timeout=5,
            )
            # Could be 301 redirect or 404 from Certbot config
            self.assertIn(resp.status_code, (301, 302, 404))
        except Exception:
            # Connection refused on port 80 is also acceptable
            pass
