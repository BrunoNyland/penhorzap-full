"""Testes do classificador puro (WS-D2).

Cobre a garantia dura de que `extrair_intencao` nunca levanta (mesmo sem
`GEMINI_API_KEY`) e o invariante de privacidade: o prompt montado para o
Gemini nunca contém valores financeiros de contrato nem respostas de FAQ --
só o necessário para desambiguar (número/vencimento/parcelado; id+pergunta).
"""

from django.test import TestCase, override_settings

from ia.schemas import ClassificacaoLote
from ia.services import _formatar_contratos, _formatar_faqs, _montar_prompt, extrair_intencao


class ExtrairIntencaoSemApiKeyTests(TestCase):
    @override_settings(GEMINI_API_KEY="")
    def test_sem_api_key_retorna_fallback_neutro_sem_levantar(self):
        resultado = extrair_intencao(
            "quero renovar meu contrato",
            [],
            [],
            [],
            identificado=True,
            db_atualizada=True,
            contato_tipo="cliente",
        )
        self.assertIsInstance(resultado, ClassificacaoLote)
        self.assertTrue(resultado.precisa_humano)

    @override_settings(GEMINI_API_KEY="")
    def test_sem_api_key_nao_levanta_mesmo_com_entrada_vazia(self):
        # Garantia dura: nenhuma combinação de entrada pode fazer levantar.
        resultado = extrair_intencao(
            "", [], [], [], identificado=False, db_atualizada=False, contato_tipo="desconhecido"
        )
        self.assertIsInstance(resultado, ClassificacaoLote)
        self.assertTrue(resultado.precisa_humano)

    @override_settings(GEMINI_API_KEY="")
    def test_sem_api_key_aceita_lote_de_mensagens_como_lista(self):
        # `mensagens_lote` aceita list[str] (lote de N mensagens não
        # respondidas) além de str única -- forma que a Fase 3/debounce vai
        # passar a usar.
        resultado = extrair_intencao(
            ["oi", "quero renovar meu contrato"],
            [],
            [],
            [],
            identificado=True,
            db_atualizada=True,
            contato_tipo="cliente",
        )
        self.assertIsInstance(resultado, ClassificacaoLote)
        self.assertTrue(resultado.precisa_humano)


class PrivacidadeDoPromptTests(TestCase):
    """A IA é um classificador puro: nunca deve ver valores financeiros de
    contrato nem o texto de respostas de FAQ (só id+pergunta)."""

    def _contrato_fake(self):
        # Valores distintos e "marcantes" o suficiente para não colidirem
        # por acaso com nenhum outro número do prompt (vencimento, ids etc).
        return {
            "contrato": "C777",
            "data_vencimento": "2026-08-01",
            "parcelado": True,
            "vlr_emprestimo": "913131.13",
            "vlr_liquido": "824242.24",
            "liquidacao": "R$606.060,60",
            "vlr_renovacao_30": "735353.35",
            "vlr_renovacao_60": "646464.46",
            "vlr_renovacao_90": "557575.57",
            "vlr_renovacao_120": "468686.68",
            "vlr_renovacao_150": "379797.79",
            "vlr_renovacao_180": "281818.18",
            "vlr_parcela": "192929.29",
        }

    def test_formatar_contratos_nao_contem_valores_financeiros(self):
        contrato = self._contrato_fake()
        texto = _formatar_contratos([contrato])

        self.assertIn("C777", texto)
        self.assertIn("2026-08-01", texto)

        valores_financeiros = [
            contrato["vlr_emprestimo"],
            contrato["vlr_liquido"],
            contrato["liquidacao"],
            contrato["vlr_renovacao_30"],
            contrato["vlr_renovacao_60"],
            contrato["vlr_renovacao_90"],
            contrato["vlr_renovacao_120"],
            contrato["vlr_renovacao_150"],
            contrato["vlr_renovacao_180"],
            contrato["vlr_parcela"],
        ]
        for valor in valores_financeiros:
            self.assertNotIn(valor, texto, f"valor financeiro {valor!r} vazou para o prompt da IA")

    def test_montar_prompt_completo_nao_contem_valores_financeiros(self):
        contrato = self._contrato_fake()
        faqs = [{"id": 1, "pergunta": "Vocês aceitam relógio?"}]
        prompt = _montar_prompt(
            "quero renovar",
            [{"direcao": "in", "texto": "oi"}],
            [contrato],
            faqs,
            identificado=True,
            db_atualizada=True,
            contato_tipo="cliente",
        )
        valores_financeiros = [
            contrato["vlr_emprestimo"],
            contrato["vlr_liquido"],
            contrato["liquidacao"],
            contrato["vlr_renovacao_30"],
            contrato["vlr_renovacao_60"],
            contrato["vlr_renovacao_90"],
            contrato["vlr_renovacao_120"],
            contrato["vlr_renovacao_150"],
            contrato["vlr_renovacao_180"],
            contrato["vlr_parcela"],
        ]
        for valor in valores_financeiros:
            self.assertNotIn(
                valor, prompt, f"valor financeiro {valor!r} vazou para o prompt completo da IA"
            )

    def test_formatar_faqs_so_id_e_pergunta_nunca_resposta(self):
        faqs = [
            {
                "id": 1,
                "pergunta": "Vocês aceitam relógio?",
                "resposta": "SEGREDO_RESPOSTA_NAO_DEVE_VAZAR",
            },
            {"id": 2, "pergunta": "Qual o horário de funcionamento?"},
        ]
        texto = _formatar_faqs(faqs)
        self.assertIn("Vocês aceitam relógio?", texto)
        self.assertIn("Qual o horário de funcionamento?", texto)
        self.assertIn("1", texto)
        self.assertIn("2", texto)
        self.assertNotIn("SEGREDO_RESPOSTA_NAO_DEVE_VAZAR", texto)

    def test_formatar_faqs_com_respostas_incluidas(self):
        faqs = [
            {
                "id": 1,
                "pergunta": "Vocês aceitam relógio?",
                "respostas": ["Aceitamos relógios de ouro.", "Outros sob consulta."],
            }
        ]
        texto = _formatar_faqs(faqs)
        self.assertIn("Vocês aceitam relógio?", texto)
        self.assertIn("Aceitamos relógios de ouro. | Outros sob consulta.", texto)

    def test_formatar_contratos_sem_contratos(self):
        self.assertIn("sem contratos ativos", _formatar_contratos([]))

    def test_formatar_faqs_sem_faqs(self):
        self.assertIn("sem FAQ cadastrado", _formatar_faqs([]))

    def test_montar_prompt_lote_numera_mensagens_em_ordem(self):
        prompt = _montar_prompt(
            ["bom dia", "quero renovar o contrato"],
            [],
            [],
            [],
            identificado=True,
            db_atualizada=True,
            contato_tipo="cliente",
        )
        self.assertIn("MENSAGENS DO CLIENTE (não respondidas, em ordem):", prompt)
        self.assertIn("1. bom dia", prompt)
        self.assertIn("2. quero renovar o contrato", prompt)
        # a seção antiga (single-mensagem) não deve mais existir
        self.assertNotIn("MENSAGEM ATUAL DO CLIENTE:", prompt)

    def test_montar_prompt_lote_com_duas_mensagens_nao_contem_valores_financeiros(self):
        contrato = self._contrato_fake()
        faqs = [{"id": 1, "pergunta": "Vocês aceitam relógio?"}]
        prompt = _montar_prompt(
            ["bom dia", "quero renovar"],
            [{"direcao": "in", "texto": "oi"}],
            [contrato],
            faqs,
            identificado=True,
            db_atualizada=True,
            contato_tipo="cliente",
        )
        valores_financeiros = [
            contrato["vlr_emprestimo"],
            contrato["vlr_liquido"],
            contrato["liquidacao"],
            contrato["vlr_renovacao_30"],
            contrato["vlr_renovacao_60"],
            contrato["vlr_renovacao_90"],
            contrato["vlr_renovacao_120"],
            contrato["vlr_renovacao_150"],
            contrato["vlr_renovacao_180"],
            contrato["vlr_parcela"],
        ]
        for valor in valores_financeiros:
            self.assertNotIn(
                valor, prompt, f"valor financeiro {valor!r} vazou para o prompt do lote"
            )
