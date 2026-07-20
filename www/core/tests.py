"""Testes de funções puras/models estáveis de core.

Escopo (WS-D1): utils.py (validar_cpf, parse_nome_salvo), BotConfig,
FAQSugerida, Cliente.buscar_por_cpf e MensagensConfig.get_solo(). Nada de
whatsapp/tasks.py nem ia/ aqui — ver whatsapp/tests.py e ia/tests.py
(propriedade de outro workstream).
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import BotConfig, Cliente, FAQSugerida, MensagensConfig
from core.utils import parse_br_decimal, parse_nome_salvo, validar_cpf


class ValidarCpfTests(TestCase):
    def test_cpf_valido(self):
        # CPF válido conhecido (dígitos verificadores corretos).
        self.assertTrue(validar_cpf("52998224725"))

    def test_cpf_valido_formatado_com_pontuacao(self):
        self.assertTrue(validar_cpf("529.982.247-25"))

    def test_cpf_checksum_invalido(self):
        self.assertFalse(validar_cpf("52998224726"))

    def test_cpf_todos_digitos_iguais(self):
        self.assertFalse(validar_cpf("11111111111"))
        self.assertFalse(validar_cpf("00000000000"))

    def test_cpf_tamanho_errado(self):
        self.assertFalse(validar_cpf("1234567890"))
        self.assertFalse(validar_cpf("123456789012"))

    def test_cpf_vazio_ou_none(self):
        self.assertFalse(validar_cpf(""))
        self.assertFalse(validar_cpf(None))

    def test_cpf_curto(self):
        self.assertFalse(validar_cpf("123"))

    def test_cpf_nunca_levanta_com_lixo(self):
        # Nunca deve levantar exceção mesmo com entrada não numérica/estranha.
        self.assertFalse(validar_cpf("abc.def.ghi-jk"))
        self.assertFalse(validar_cpf("!@#$%^&*()__"))


class ParseNomeSalvoTests(TestCase):
    def test_padrao_phn_cpf_nome(self):
        cpf, nome = parse_nome_salvo("PHN_52998224725_Joao da Silva")
        self.assertEqual(cpf, "52998224725")
        self.assertEqual(nome, "Joao da Silva")

    def test_padrao_phn_case_insensitive_no_prefixo(self):
        cpf, nome = parse_nome_salvo("phn_52998224725_Maria")
        self.assertEqual(cpf, "52998224725")
        self.assertEqual(nome, "Maria")

    def test_padrao_phn_sem_nome_apos_cpf(self):
        cpf, nome = parse_nome_salvo("PHN_52998224725")
        self.assertEqual(cpf, "52998224725")
        self.assertEqual(nome, "")

    def test_padrao_phn_sem_underscore_entre_cpf_e_nome(self):
        cpf, nome = parse_nome_salvo("PHN_52998224725Joao")
        self.assertEqual(cpf, "52998224725")
        self.assertEqual(nome, "Joao")

    def test_nome_sem_prefixo_phn_retorna_none(self):
        cpf, nome = parse_nome_salvo("Joao da Silva")
        self.assertIsNone(cpf)
        self.assertIsNone(nome)

    def test_nome_vazio_ou_none_retorna_none(self):
        self.assertEqual(parse_nome_salvo(""), (None, None))
        self.assertEqual(parse_nome_salvo(None), (None, None))

    def test_prefixo_phn_sem_cpf_valido_retorna_none(self):
        # Menos de 11 dígitos após o prefixo não é reconhecido como PHN_.
        cpf, nome = parse_nome_salvo("PHN_1234_Nome")
        self.assertIsNone(cpf)
        self.assertIsNone(nome)

    def test_nome_com_espacos_extras_no_meio(self):
        cpf, nome = parse_nome_salvo("PHN_ 52998224725 _ Joao   da Silva")
        self.assertEqual(cpf, "52998224725")
        self.assertEqual(nome, "Joao   da Silva")


class BotConfigDatabaseAtualizadaTests(TestCase):
    def test_sem_ultima_atualizacao_dados_e_falsa(self):
        config = BotConfig(ultima_atualizacao_dados=None, freshness_horas=24)
        self.assertFalse(config.database_atualizada())

    def test_atualizacao_fresca_dentro_da_janela(self):
        agora = timezone.now()
        config = BotConfig(
            ultima_atualizacao_dados=agora - timedelta(hours=1),
            freshness_horas=24,
        )
        self.assertTrue(config.database_atualizada(agora=agora))

    def test_atualizacao_expirada_fora_da_janela(self):
        agora = timezone.now()
        config = BotConfig(
            ultima_atualizacao_dados=agora - timedelta(hours=25),
            freshness_horas=24,
        )
        self.assertFalse(config.database_atualizada(agora=agora))

    def test_atualizacao_exatamente_no_limite_e_fresca(self):
        agora = timezone.now()
        config = BotConfig(
            ultima_atualizacao_dados=agora - timedelta(hours=24),
            freshness_horas=24,
        )
        self.assertTrue(config.database_atualizada(agora=agora))

    def test_get_solo_cria_singleton_pk_1(self):
        config = BotConfig.get_solo()
        self.assertEqual(config.pk, 1)
        # Segunda chamada retorna a mesma instância (não duplica).
        self.assertEqual(BotConfig.objects.count(), 1)
        config2 = BotConfig.get_solo()
        self.assertEqual(config2.pk, config.pk)


class FAQSugeridaRegistrarTests(TestCase):
    # Nota: usamos texto sem acentuação nas perguntas de teste porque o
    # `UPPER()`/`LOWER()` do SQLite (backend de teste) só faz case-fold ASCII;
    # "á" vs "Á" não colapsam via `iexact` nesse backend (MySQL em produção
    # não tem essa limitação). O teste cobre a semântica de case-insensitivity
    # do método, não a colação de acentos do banco.
    def test_registrar_cria_pendente(self):
        sugestao = FAQSugerida.registrar("Qual o horario de atendimento?")
        self.assertEqual(sugestao.status, FAQSugerida.Status.PENDENTE)
        self.assertEqual(sugestao.ocorrencias, 1)
        self.assertEqual(FAQSugerida.objects.count(), 1)

    def test_pergunta_repetida_case_diferente_incrementa_ocorrencias(self):
        primeira = FAQSugerida.registrar("Qual o horario de atendimento?")
        segunda = FAQSugerida.registrar("QUAL O HORARIO DE ATENDIMENTO?")

        self.assertEqual(primeira.pk, segunda.pk)
        self.assertEqual(segunda.ocorrencias, 2)
        self.assertEqual(FAQSugerida.objects.count(), 1)

    def test_pergunta_igual_mas_aprovada_cria_nova_pendente(self):
        aprovada = FAQSugerida.registrar("Qual o horario de atendimento?")
        aprovada.status = FAQSugerida.Status.APROVADA
        aprovada.save(update_fields=["status"])

        nova = FAQSugerida.registrar("Qual o horario de atendimento?")

        self.assertNotEqual(aprovada.pk, nova.pk)
        self.assertEqual(nova.status, FAQSugerida.Status.PENDENTE)
        self.assertEqual(nova.ocorrencias, 1)
        self.assertEqual(FAQSugerida.objects.count(), 2)

    def test_registrar_associa_conversa_e_pergunta_original(self):
        from core.models import Conversa

        conversa = Conversa.objects.create(remote_jid="5567999999999@s.whatsapp.net")
        sugestao = FAQSugerida.registrar(
            "Posso pagar em dinheiro?",
            conversa=conversa,
            pergunta_original="Ei, da pra pagar em dinheiro vivo?",
        )
        self.assertEqual(sugestao.conversa_id, conversa.pk)
        self.assertEqual(sugestao.pergunta_original, "Ei, da pra pagar em dinheiro vivo?")


class ClienteBuscarPorCpfTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(cpf="52998224725", nome="Joao da Silva")

    def test_busca_por_cpf_limpo(self):
        encontrado = Cliente.buscar_por_cpf("52998224725")
        self.assertEqual(encontrado, self.cliente)

    def test_busca_por_cpf_pontuado(self):
        encontrado = Cliente.buscar_por_cpf("529.982.247-25")
        self.assertEqual(encontrado, self.cliente)

    def test_busca_por_cpf_inexistente_retorna_none(self):
        self.assertIsNone(Cliente.buscar_por_cpf("11144477735"))

    def test_busca_com_cpf_vazio_retorna_none(self):
        self.assertIsNone(Cliente.buscar_por_cpf(""))
        self.assertIsNone(Cliente.buscar_por_cpf(None))


class MensagensConfigGetSoloTests(TestCase):
    def test_get_solo_cria_singleton_pk_1(self):
        config = MensagensConfig.get_solo()
        self.assertEqual(config.pk, 1)
        self.assertEqual(MensagensConfig.objects.count(), 1)
        config2 = MensagensConfig.get_solo()
        self.assertEqual(config2.pk, config.pk)

    def test_defaults_de_templates_novos_nao_estao_vazios(self):
        config = MensagensConfig.get_solo()
        campos_tpl = [
            "tpl_saudacao_cliente",
            "tpl_saudacao_cliente_com_pedido",
            "tpl_contrato_vencimento",
            "tpl_contrato_renovacao",
            "tpl_contrato_quitacao",
            "tpl_contrato_parcela",
            "tpl_contrato_resumo",
            "tpl_contrato_laudo",
            "tpl_lista_header",
            "tpl_intro_vencimento",
            "tpl_intro_renovacao",
            "tpl_intro_quitacao",
            "tpl_intro_parcela",
            "tpl_intro_lista",
            "tpl_intro_laudo",
            "tpl_totalizador",
            "tpl_totalizador_geral",
            "msg_fallback_sem_resposta",
            "msg_info_negada_desconhecido",
            "msg_midia_nao_suportada",
            "msg_duvida_anotada",
            "msg_saudacao_com_pedido",
            "msg_pedir_campo_valor_filtro",
        ]
        for campo in campos_tpl:
            valor = getattr(config, campo)
            self.assertTrue(valor and valor.strip(), f"{campo} não deveria estar vazio")


class ParseBrDecimalTests(TestCase):
    def test_parse_simple_decimal(self):
        self.assertEqual(parse_br_decimal("1.234,56"), Decimal("1234.56"))

    def test_parse_with_currency_prefix_and_space(self):
        self.assertEqual(parse_br_decimal("R$ 1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_br_decimal("R$1.234,56"), Decimal("1234.56"))

    def test_parse_with_suffix_and_space(self):
        self.assertEqual(parse_br_decimal("R$764,46 C"), Decimal("764.46"))
        self.assertEqual(parse_br_decimal("R$ 2.140,84 C"), Decimal("2140.84"))
        self.assertEqual(parse_br_decimal("100,00 D"), Decimal("100.00"))

    def test_parse_invalid(self):
        self.assertIsNone(parse_br_decimal("abc"))
        self.assertIsNone(parse_br_decimal(""))
        self.assertIsNone(parse_br_decimal(None))


class ImportarSqliteArquivoTests(TestCase):
    def setUp(self):
        import sqlite3
        import tempfile

        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_path = self.temp_file.name
        self.temp_file.close()

        # Connect and create tables
        conn = sqlite3.connect(self.temp_path)

        conn.execute("""
            CREATE TABLE agencias_penhor (
                codigo TEXT PRIMARY KEY, dv TEXT, nome TEXT, uf TEXT, situacao TEXT,
                tipo TEXT, porte TEXT, penhor TEXT, logradouro TEXT, bairro TEXT,
                cidade TEXT, cep TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE licitacoes (
                numero TEXT PRIMARY KEY, situacao TEXT, centralizadora TEXT, data TEXT,
                uf TEXT, local_retirada TEXT, periodo_retirada TEXT, periodo_lances TEXT,
                periodo_exposicao TEXT, participantes TEXT, urls_arquivos TEXT, data_limite_pagamento TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE clientes (
                cpf TEXT PRIMARY KEY, nome TEXT, situacao_do_cpf TEXT, situacao_do_cadastro TEXT,
                logradouro TEXT, bairro TEXT, cidade TEXT, cep TEXT, aniversario TEXT,
                data_da_captura_das_renovacoes TEXT, documento TEXT, boleto_emitido TEXT,
                conta_nsgd TEXT, codigo_de_barras TEXT, codigo_sipen TEXT, cocli TEXT,
                limite_especial TEXT, emails TEXT, telefones TEXT, contratos_parcelados TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE contratos (
                contrato TEXT PRIMARY KEY, cpf TEXT, nome TEXT, data_emissao TEXT, data_vencimento TEXT,
                data_situacao TEXT, data_tva TEXT, data_entrega_garantia TEXT, data_dos_dados TEXT,
                data_do_laudo TEXT, prazo TEXT, atraso TEXT, situacao TEXT, situacao_codigo TEXT,
                modalidade TEXT, acerto_de_valores TEXT, avaliador TEXT, matricula_avaliador TEXT,
                depesas_vinculadas TEXT, faixa TEXT, liquidacao TEXT, qt_parcelas TEXT,
                qt_parcelas_pagas TEXT, qt_renovacoes TEXT, vlr_avaliacao TEXT, vlr_emprestimo TEXT,
                vlr_atualizacao_monetaria TEXT, vlr_desconto TEXT, vlr_iof TEXT, vlr_juros TEXT,
                vlr_liquido TEXT, vlr_maximo_emprestimo TEXT, vlr_mora TEXT, vlr_multa TEXT,
                vlr_rem_atraso TEXT, vlr_renovacao_30 TEXT, vlr_renovacao_60 TEXT, vlr_renovacao_90 TEXT,
                vlr_renovacao_120 TEXT, vlr_renovacao_150 TEXT, vlr_renovacao_180 TEXT, vlr_tar TEXT,
                vlr_troco TEXT, vlr_parcela TEXT, vlr_parcela_atualizada TEXT, tarifa_custodia TEXT,
                fator_de_atualizacao_avaliacao TEXT, margem TEXT, peso TEXT, valor_p_grama TEXT, laudo TEXT
            )
        """)

        # Insert one mock row per table
        conn.execute("""
            INSERT INTO agencias_penhor VALUES ('0886', '0', 'Agencia Centro', 'MS', 'ATIVA', 'AGENCIA', 'MEDIO', 'SIM', 'Rua 14', 'Centro', 'Campo Grande', '79000-000')
        """)
        conn.execute("""
            INSERT INTO licitacoes VALUES ('2026/001', 'ABERTA', 'CENTRAL', '10/10/2026', 'MS', 'Agencia', '10-12', '12-14', '14-16', 'Participantes', 'url', '15/10/2026')
        """)
        conn.execute("""
            INSERT INTO clientes VALUES (
                '52998224725', 'JOAO SILVA', 'REGULAR', 'COMPLETO', 'Rua A', 'Bairro B', 'Campo Grande', '79000-001',
                '01/01/1980', '15/07/2026', 'RG 123', 'S', '123', 'bar', 'sip', 'coc', '1.000,00', "['joao@test.com']", "['67999755980']", "['9999']"
            )
        """)
        conn.execute("""
            INSERT INTO contratos VALUES (
                '9999', '52998224725', 'JOAO SILVA', '01/01/2026', '01/05/2026', '01/05/2026', '01/05/2026', '01/05/2026',
                '01/05/2026', '01/05/2026', '120', '10', 'EM ABERTO', 'EMAB', 'MOD', '0', 'AVAL', '1234', '0', 'FAIXA',
                '2.000,00', '1', '0', '0', '5.000,00', '1.500,00', '0', '0', '30,00', '50,00', '1.400,00', '2.000,00',
                '0', '0', '0', '100,00', '200,00', '300,00', '400,00', '500,00', '600,00', '10,00', '0', '0', '0', '0',
                '1,0', '0', '10,5', '150,00', 'Joia de ouro'
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        import os

        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)

    def test_importar_sqlite_sucesso(self):
        from core.models import AgenciaPenhor, ContratoPenhor, Conversa, Licitacao, Telefone
        from core.services import importar_sqlite_arquivo

        # Create a conversation to test reassociation
        conversa = Conversa.objects.create(remote_jid="5567999755980@s.whatsapp.net")

        counts = importar_sqlite_arquivo(self.temp_path)
        self.assertEqual(counts["agencias_penhor"], 1)
        self.assertEqual(counts["licitacoes"], 1)
        self.assertEqual(counts["clientes"], 1)
        self.assertEqual(counts["telefones"], 1)
        self.assertEqual(counts["contratos"], 1)

        # Assert data was imported correctly
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(ContratoPenhor.objects.count(), 1)
        self.assertEqual(AgenciaPenhor.objects.count(), 1)
        self.assertEqual(Licitacao.objects.count(), 1)
        self.assertEqual(Telefone.objects.count(), 1)

        # Assert conversation was reassociated to client
        conversa.refresh_from_db()
        self.assertEqual(conversa.cliente_id, "52998224725")
