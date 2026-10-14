"""
Plataforma de testes adversariais do bot: roda uma bateria de mensagens
"difíceis" (mal escritas, fora de ordem, ambíguas, contraditórias) contra o
pipeline real de classificação (extrair_intencao) + renderização
(_montar_resposta_simulador) para uma amostra de clientes reais, sem enviar
nada de verdade pelo WhatsApp e sem criar Solicitacao no banco.

Cada cenário é conferido contra um conjunto de invariantes genéricas (nunca
inventar contrato, nunca criar solicitação com tipo indefinido, nunca mostrar
um valor e perguntar o tipo do boleto na mesma resposta etc.) e, quando
aplicável, uma checagem específica do cenário (ex.: pergunta de completude
deve virar lista_contratos; reclamação repetida deve marcar precisa_humano).

Uso:
    python manage.py testar_cenarios_bot
    python manage.py testar_cenarios_bot --clientes 5
    python manage.py testar_cenarios_bot --cpf 847.422.321-00 --cpf 270.709.078-69
    python manage.py testar_cenarios_bot --seed 42 --verbose
"""

import random
import re
import time

from django.core.management.base import BaseCommand
from django.core.management.color import no_style

from core.models import FAQ, SITUACOES_LIQUIDADAS_COD, Cliente, ContratoPenhor, MensagensConfig
from ia.schemas import InfoContrato, TipoPagamento
from ia.services import extrair_intencao
from whatsapp.tasks import _contratos_ativos_values

CONTRATO_RE = re.compile(r"\d{4}\.\d{3}\.\d{8}-\d")


def _turno_unico(*mensagens):
    """Cenário de 1 turno (as mensagens chegam juntas, mesmo lote/debounce)."""
    return [list(mensagens)]


SCENARIOS = [
    {
        "id": "vaga_sem_pedido",
        "descricao": 'Mensagem solta sem pedido nenhum: "Oi"',
        "turnos": _turno_unico("Oi"),
    },
    {
        "id": "fora_de_ordem",
        "descricao": "Cliente responde o prazo antes de dizer que quer renovar",
        "turnos": [["60 dias"], ["Ah, quero renovar por favor"]],
    },
    {
        "id": "ambigua_sem_contrato_nem_tipo",
        "descricao": '"Quero pagar" sem dizer qual contrato nem o tipo',
        "turnos": _turno_unico("Quero pagar"),
    },
    {
        "id": "valor_puro",
        "descricao": "Pergunta só o valor, sem pedir o boleto (regressão)",
        "turnos": _turno_unico("Quanto que tá pra pagar?"),
    },
    {
        "id": "completude_contratos",
        "descricao": "Pergunta de confirmação de completude (regressão)",
        "turnos": _turno_unico("Isso é tudo que eu tenho de contrato?"),
    },
    {
        "id": "contrato_inexistente",
        "descricao": "Cita um número de contrato que não existe",
        "turnos": _turno_unico("Quero renovar o contrato 0000.000.00000000-0"),
    },
    {
        "id": "erros_digitacao",
        "descricao": "Texto com erros de digitação e abreviações",
        "turnos": _turno_unico("oq qe eu tenho pra pagar msm, qnto ta pra quitr pfvr"),
    },
    {
        "id": "multi_intencao",
        "descricao": "Saudação + FAQ + pedido de contrato na mesma mensagem",
        "turnos": _turno_unico(
            "Bom dia! Vocês aceitam pagamento via Pix? E qual o valor pra renovar por 90 dias?"
        ),
    },
    {
        "id": "cliente_irritado",
        "descricao": "Reclamação com sinal claro de irritação/insistência",
        "turnos": _turno_unico(
            "Já é a terceira vez que mando mensagem hoje e ninguém me responde, isso é um absurdo"
        ),
    },
    {
        "id": "fora_de_escopo",
        "descricao": "Pergunta fora do escopo do penhor",
        "turnos": _turno_unico("Vocês fazem empréstimo consignado também?"),
    },
    {
        "id": "agradecimento_despedida",
        "descricao": "Só agradecimento/despedida, sem pedido nenhum (regressão)",
        "turnos": _turno_unico("Feito o pagamento, obrigada! Deus abençoe"),
    },
]


def _contem_contrato_inventado(texto, contratos_validos, contratos_citados_pelo_cliente):
    for numero in CONTRATO_RE.findall(texto):
        if numero in contratos_validos:
            continue
        if numero in contratos_citados_pelo_cliente:
            # cliente citou um contrato que não existe -- ok o bot ecoar/rejeitar,
            # não conta como "inventado" pelo bot.
            continue
        return numero
    return None


def _contem_contradicao_valor_e_pergunta_tipo(respostas):
    tem_valor_especifico = any(
        ("Liquidação:" in r or "Renovação" in r or "parcela:" in r.lower()) for r in respostas
    )
    tem_pergunta_tipo = any("renovação? ou quitação?" in r.lower() for r in respostas)
    return tem_valor_especifico and tem_pergunta_tipo


def _checar_invariantes_genericas(resultado, respostas, contratos_ativos, mensagens_cliente):
    problemas = []
    numeros_validos = {c["contrato"] for c in contratos_ativos}
    numeros_citados_cliente = set()
    for msg in mensagens_cliente:
        numeros_citados_cliente.update(CONTRATO_RE.findall(msg))

    texto_completo = "\n".join(respostas)

    inventado = _contem_contrato_inventado(texto_completo, numeros_validos, numeros_citados_cliente)
    if inventado:
        problemas.append(f"contrato '{inventado}' não pertence aos contratos ativos do cliente")

    if _contem_contradicao_valor_e_pergunta_tipo(respostas):
        problemas.append(
            "mostrou um valor específico e perguntou 'renovação ou quitação?' na mesma resposta"
        )

    tem_indefinido = any(d.tipo == TipoPagamento.INDEFINIDO for d in resultado.solicitacoes)
    if resultado.pronto_para_criar_solicitacao and tem_indefinido:
        problemas.append("pronto_para_criar_solicitacao=true com tipo indefinido")

    if not respostas:
        problemas.append("resposta vazia (nenhuma bolha gerada)")

    return problemas


SCENARIO_CHECKS = {
    "completude_contratos": lambda resultado, respostas: (
        []
        if any(i.info == InfoContrato.LISTA_CONTRATOS for i in resultado.infos_contrato)
        else ["esperava infos_contrato=lista_contratos e não veio"]
    ),
    "cliente_irritado": lambda resultado, respostas: (
        [] if resultado.precisa_humano else ["esperava precisa_humano=true e veio false"]
    ),
    "contrato_inexistente": lambda resultado, respostas: (
        []
        if not any(
            "0000.000.00000000-0" in r and "*Contrato*" in r for r in respostas
        )
        else ["tratou o contrato inexistente como se fosse um contrato válido"]
    ),
    "agradecimento_despedida": lambda resultado, respostas: (
        []
        if resultado.cortesia_sem_pedido
        and not any("Boa pergunta! Deixa eu verificar" in r for r in respostas)
        else ["esperava cortesia_sem_pedido=true e reconhecimento curto, não o fallback de dúvida"]
    ),
}


class Command(BaseCommand):
    help = (
        "Roda uma bateria de mensagens adversariais (vagas, fora de ordem, ambíguas, "
        "mal escritas) contra o classificador do bot para uma amostra de clientes "
        "reais e reporta PASSOU/FALHOU por cenário. Não envia nada pelo WhatsApp "
        "nem cria Solicitacao no banco -- é só leitura + chamada real à IA."
    )

    def add_arguments(self, parser):
        parser.add_argument("--clientes", type=int, default=10, help="Quantos clientes aleatórios testar (default: 10).")
        parser.add_argument(
            "--cpf",
            action="append",
            default=None,
            help="Testa um CPF específico em vez de sortear (pode repetir --cpf várias vezes).",
        )
        parser.add_argument("--seed", type=int, default=None, help="Semente do sorteio, pra repetir a mesma amostra.")
        parser.add_argument(
            "--verbose", action="store_true", help="Mostra a transcrição completa de todo cenário, não só das falhas."
        )
        parser.add_argument(
            "--pausa",
            type=float,
            default=4.5,
            help=(
                "Segundos de pausa entre chamadas à Gemini, pra não estourar o rate "
                "limit do free tier (15 req/min). Default: 4.5s."
            ),
        )

    def handle(self, *args, **options):
        style = self.style or no_style()

        if options["cpf"]:
            clientes = list(Cliente.objects.filter(cpf__in=options["cpf"]))
            faltando = set(options["cpf"]) - {c.cpf for c in clientes}
            for cpf in faltando:
                self.stderr.write(style.WARNING(f"CPF não encontrado: {cpf}"))
        else:
            if options["seed"] is not None:
                random.seed(options["seed"])
            cliente_ids = list(
                ContratoPenhor.objects.exclude(situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
                .exclude(situacao__icontains="Liquidado")
                .values_list("cliente_id", flat=True)
                .distinct()
            )
            if not cliente_ids:
                self.stderr.write(style.ERROR("Nenhum cliente com contrato ativo encontrado."))
                return
            amostra = random.sample(cliente_ids, min(options["clientes"], len(cliente_ids)))
            clientes = list(Cliente.objects.filter(cpf__in=amostra))

        faqs = list(FAQ.objects.filter(ativo=True).values("id", "pergunta"))
        msgs = MensagensConfig.get_solo()

        total = 0
        total_falhas = 0
        total_pulados = 0
        falhas_resumo = []
        pulados_resumo = []
        primeira_chamada = True

        for cliente in clientes:
            contratos_ativos = _contratos_ativos_values(cliente)
            self.stdout.write("")
            self.stdout.write(
                style.MIGRATE_HEADING(
                    f"=== {cliente.nome} ({cliente.cpf}) -- {len(contratos_ativos)} contrato(s) ativo(s) ==="
                )
            )

            for cenario in SCENARIOS:
                total += 1
                from api.views import _montar_resposta_simulador

                historico = []
                respostas_todos_turnos = []
                mensagens_cliente = []
                resultado = None
                erro = None
                caiu_no_fallback = False

                try:
                    for turno in cenario["turnos"]:
                        mensagens_cliente.extend(turno)
                        if not primeira_chamada:
                            time.sleep(options["pausa"])
                        primeira_chamada = False
                        resultado = extrair_intencao(
                            turno,
                            historico,
                            contratos_ativos,
                            faqs,
                            identificado=True,
                            db_atualizada=True,
                            contato_tipo="cliente",
                        )
                        raw_resp = getattr(resultado, "_raw_response", "") or ""
                        if raw_resp.startswith("Fallback:") or raw_resp.startswith("Erro ao chamar Gemini"):
                            caiu_no_fallback = True
                        respostas = _montar_resposta_simulador(resultado, cliente, msgs)
                        respostas_todos_turnos.extend(respostas)
                        for texto in turno:
                            historico.append({"direcao": "in", "texto": texto})
                        for texto in respostas:
                            historico.append({"direcao": "out", "texto": texto})
                except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer exceção do pipeline
                    erro = f"{type(exc).__name__}: {exc}"

                if erro:
                    total_falhas += 1
                    falhas_resumo.append(
                        f"{cliente.nome} ({cliente.cpf}) / {cenario['id']}: exceção durante o processamento: {erro}"
                    )
                    self.stdout.write(f"  [{style.ERROR('FALHOU')}] {cenario['id']} -- {cenario['descricao']}")
                    self.stdout.write(style.ERROR(f"         -> exceção: {erro}"))
                    continue

                if caiu_no_fallback:
                    total_pulados += 1
                    pulados_resumo.append(f"{cliente.nome} ({cliente.cpf}) / {cenario['id']}")
                    self.stdout.write(
                        f"  [{style.WARNING('PULADO')}] {cenario['id']} -- {cenario['descricao']} "
                        "(Gemini indisponível/rate limit nesta chamada, não testado de verdade)"
                    )
                    continue

                problemas = _checar_invariantes_genericas(
                    resultado, respostas_todos_turnos, contratos_ativos, mensagens_cliente
                )
                check_especifico = SCENARIO_CHECKS.get(cenario["id"])
                if check_especifico:
                    problemas.extend(check_especifico(resultado, respostas_todos_turnos))

                passou = not problemas
                if not passou:
                    total_falhas += 1
                    falhas_resumo.append(
                        f"{cliente.nome} ({cliente.cpf}) / {cenario['id']}: {'; '.join(problemas)}"
                    )

                tag = style.SUCCESS("PASSOU") if passou else style.ERROR("FALHOU")
                self.stdout.write(f"  [{tag}] {cenario['id']} -- {cenario['descricao']}")
                if not passou:
                    for p in problemas:
                        self.stdout.write(style.ERROR(f"         -> {p}"))

                if options["verbose"] or not passou:
                    for linha in mensagens_cliente:
                        self.stdout.write(f"         cliente: {linha}")
                    for linha in respostas_todos_turnos:
                        self.stdout.write(f"         bot: {linha}".replace("\n", "\n              "))

        avaliados = total - total_pulados
        self.stdout.write("")
        self.stdout.write(
            style.MIGRATE_HEADING(
                f"=== Resumo: {avaliados - total_falhas}/{avaliados} cenários avaliados passaram "
                f"({total_pulados} pulado(s) por indisponibilidade da Gemini) ==="
            )
        )
        if falhas_resumo:
            self.stdout.write(style.ERROR(f"{total_falhas} falha(s):"))
            for linha in falhas_resumo:
                self.stdout.write(style.ERROR(f"  - {linha}"))
        if pulados_resumo:
            self.stdout.write(style.WARNING(f"{total_pulados} pulado(s) (rode de novo pra cobrir):"))
            for linha in pulados_resumo:
                self.stdout.write(style.WARNING(f"  - {linha}"))
