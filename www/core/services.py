import sqlite3

from django.db import transaction
from django.utils import timezone

from core.models import AgenciaPenhor, BotConfig, Cliente, ContratoPenhor, Licitacao, Telefone
from core.utils import normalize_phone_br, parse_br_date, parse_br_decimal, parse_int, parse_py_list

BATCH_SIZE = 500


def importar_sqlite_arquivo(path: str) -> dict[str, int]:
    """Abre o SQLite em `path`, importa as 4 tabelas (agencias_penhor,
    licitacoes, clientes, contratos), atualiza
    BotConfig.ultima_atualizacao_dados e retorna counts dict.
    Keys: agencias_penhor, licitacoes, clientes, telefones, contratos.
    Raises sqlite3.OperationalError etc on file errors."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    with transaction.atomic():
        # Limpar completamente clientes e contratos existentes antes de carregar os novos
        ContratoPenhor.objects.all().delete()
        Cliente.objects.all().delete()

        counts = {}
        counts["agencias_penhor"] = _import_agencias(conn)
        counts["licitacoes"] = _import_licitacoes(conn)
        counts["clientes"], counts["telefones"] = _import_clientes(conn)
        counts["contratos"] = _import_contratos(conn)

        # Reclassificar e reassociar conversas existentes aos novos clientes importados
        from core.models import Conversa
        from whatsapp.tasks import _classificar_contato
        for conversa in Conversa.objects.all():
            tipo, nome, cliente = _classificar_contato(conversa)
            conversa.tipo_contato = tipo
            conversa.nome_salvo = nome
            conversa.cliente = cliente
            conversa.save(update_fields=["tipo_contato", "nome_salvo", "cliente"])

    conn.close()

    bot = BotConfig.get_solo()
    bot.ultima_atualizacao_dados = timezone.now()
    bot.save(update_fields=["ultima_atualizacao_dados", "atualizado_em"])

    return counts


def _import_agencias(conn):
    rows = conn.execute("SELECT * FROM agencias_penhor").fetchall()
    objs = [
        AgenciaPenhor(
            codigo=r["codigo"],
            dv=r["dv"] or "",
            nome=r["nome"] or "",
            uf=r["uf"] or "",
            situacao=r["situacao"] or "",
            tipo=r["tipo"] or "",
            porte=r["porte"] or "",
            penhor=r["penhor"] or "",
            logradouro=r["logradouro"] or "",
            bairro=r["bairro"] or "",
            cidade=r["cidade"] or "",
            cep=r["cep"] or "",
        )
        for r in rows
    ]
    with transaction.atomic():
        AgenciaPenhor.objects.bulk_create(
            objs,
            batch_size=BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["codigo"],
            update_fields=[
                "dv", "nome", "uf", "situacao", "tipo", "porte", "penhor",
                "logradouro", "bairro", "cidade", "cep",
            ],
        )
    return len(objs)


def _import_licitacoes(conn):
    rows = conn.execute("SELECT * FROM licitacoes").fetchall()
    objs = [
        Licitacao(
            numero=r["numero"],
            situacao=r["situacao"] or "",
            centralizadora=r["centralizadora"] or "",
            data=r["data"] or "",
            uf=r["uf"] or "",
            local_retirada=r["local_retirada"] or "",
            periodo_retirada=r["periodo_retirada"] or "",
            periodo_lances=r["periodo_lances"] or "",
            periodo_exposicao=r["periodo_exposicao"] or "",
            participantes=r["participantes"] or "",
            urls_arquivos=r["urls_arquivos"] or "",
            data_limite_pagamento=r["data_limite_pagamento"] or "",
        )
        for r in rows
    ]
    with transaction.atomic():
        Licitacao.objects.bulk_create(
            objs,
            batch_size=BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["numero"],
            update_fields=[
                "situacao", "centralizadora", "data", "uf", "local_retirada",
                "periodo_retirada", "periodo_lances", "periodo_exposicao",
                "participantes", "urls_arquivos", "data_limite_pagamento",
            ],
        )
    return len(objs)


def _import_clientes(conn):
    rows = conn.execute("SELECT * FROM clientes").fetchall()
    objs = []
    telefones_por_cpf = {}
    for r in rows:
        emails = parse_py_list(r["emails"])
        objs.append(
            Cliente(
                cpf=r["cpf"],
                nome=r["nome"] or "",
                situacao_cpf=r["situacao_do_cpf"] or "",
                situacao_cadastro=r["situacao_do_cadastro"] or "",
                logradouro=r["logradouro"] or "",
                bairro=r["bairro"] or "",
                cidade=r["cidade"] or "",
                cep=r["cep"] or "",
                aniversario=parse_br_date(r["aniversario"]),
                data_da_captura_das_renovacoes=parse_br_date(r["data_da_captura_das_renovacoes"]),
                documento=r["documento"] or "",
                boleto_emitido=(r["boleto_emitido"] or "").strip().upper() == "S",
                conta_nsgd=r["conta_nsgd"] or "",
                codigo_de_barras=r["codigo_de_barras"] or "",
                codigo_sipen=r["codigo_sipen"] or "",
                cocli=r["cocli"] or "",
                limite_especial=parse_br_decimal(r["limite_especial"]),
                emails=emails,
            )
        )
        telefones_por_cpf[r["cpf"]] = parse_py_list(r["telefones"])

    with transaction.atomic():
        Cliente.objects.bulk_create(
            objs,
            batch_size=BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["cpf"],
            update_fields=[
                "nome", "situacao_cpf", "situacao_cadastro", "logradouro", "bairro",
                "cidade", "cep", "aniversario", "data_da_captura_das_renovacoes",
                "documento", "boleto_emitido", "conta_nsgd", "codigo_de_barras",
                "codigo_sipen", "cocli", "limite_especial", "emails",
            ],
        )

    telefone_objs = []
    cpfs_com_telefone = [cpf for cpf, nums in telefones_por_cpf.items() if nums]
    with transaction.atomic():
        Telefone.objects.filter(cliente_id__in=cpfs_com_telefone).delete()
        for cpf, numeros in telefones_por_cpf.items():
            for numero_bruto in numeros:
                normalizado = normalize_phone_br(numero_bruto)
                if not normalizado:
                    continue
                telefone_objs.append(
                    Telefone(cliente_id=cpf, numero=normalizado, numero_bruto=numero_bruto)
                )
        Telefone.objects.bulk_create(
            telefone_objs,
            batch_size=BATCH_SIZE,
            ignore_conflicts=True,
        )

    return len(objs), len(telefone_objs)


def _import_contratos(conn):
    parcelados = set()
    for (raw,) in conn.execute("SELECT contratos_parcelados FROM clientes"):
        parcelados.update(parse_py_list(raw))

    existing_cpfs = set(Cliente.objects.values_list("cpf", flat=True))

    rows = conn.execute("SELECT * FROM contratos").fetchall()
    objs = []
    for r in rows:
        cpf = r["cpf"] or ""
        objs.append(
            ContratoPenhor(
                contrato=r["contrato"],
                cliente_id=cpf if cpf in existing_cpfs else None,
                nome=r["nome"] or "",
                data_emissao=parse_br_date(r["data_emissao"]),
                data_vencimento=parse_br_date(r["data_vencimento"]),
                data_situacao=parse_br_date(r["data_situacao"]),
                data_tva=parse_br_date(r["data_tva"]),
                data_entrega_garantia=parse_br_date(r["data_entrega_garantia"]),
                data_dos_dados=parse_br_date(r["data_dos_dados"]),
                data_do_laudo=parse_br_date(r["data_do_laudo"]),
                prazo=r["prazo"] or "",
                atraso=parse_int(r["atraso"]),
                situacao=r["situacao"] or "",
                situacao_codigo=r["situacao_codigo"] or "",
                modalidade=r["modalidade"] or "",
                acerto_de_valores=r["acerto_de_valores"] or "",
                avaliador=r["avaliador"] or "",
                matricula_avaliador=r["matricula_avaliador"] or "",
                depesas_vinculadas=r["depesas_vinculadas"] or "",
                faixa=r["faixa"] or "",
                liquidacao=r["liquidacao"] or "",
                qt_parcelas=parse_int(r["qt_parcelas"]),
                qt_parcelas_pagas=parse_int(r["qt_parcelas_pagas"]),
                qt_renovacoes=parse_int(r["qt_renovacoes"]),
                parcelado=r["contrato"] in parcelados,
                vlr_avaliacao=parse_br_decimal(r["vlr_avaliacao"]),
                vlr_emprestimo=parse_br_decimal(r["vlr_emprestimo"]),
                vlr_atualizacao_monetaria=parse_br_decimal(r["vlr_atualizacao_monetaria"]),
                vlr_desconto=parse_br_decimal(r["vlr_desconto"]),
                vlr_iof=parse_br_decimal(r["vlr_iof"]),
                vlr_juros=parse_br_decimal(r["vlr_juros"]),
                vlr_liquido=parse_br_decimal(r["vlr_liquido"]),
                vlr_maximo_emprestimo=parse_br_decimal(r["vlr_maximo_emprestimo"]),
                vlr_mora=parse_br_decimal(r["vlr_mora"]),
                vlr_multa=parse_br_decimal(r["vlr_multa"]),
                vlr_rem_atraso=parse_br_decimal(r["vlr_rem_atraso"]),
                vlr_renovacao_30=parse_br_decimal(r["vlr_renovacao_30"]),
                vlr_renovacao_60=parse_br_decimal(r["vlr_renovacao_60"]),
                vlr_renovacao_90=parse_br_decimal(r["vlr_renovacao_90"]),
                vlr_renovacao_120=parse_br_decimal(r["vlr_renovacao_120"]),
                vlr_renovacao_150=parse_br_decimal(r["vlr_renovacao_150"]),
                vlr_renovacao_180=parse_br_decimal(r["vlr_renovacao_180"]),
                vlr_tar=parse_br_decimal(r["vlr_tar"]),
                vlr_troco=parse_br_decimal(r["vlr_troco"]),
                vlr_parcela=parse_br_decimal(r["vlr_parcela"]),
                vlr_parcela_atualizada=parse_br_decimal(r["vlr_parcela_atualizada"]),
                tarifa_custodia=parse_br_decimal(r["tarifa_custodia"]),
                fator_de_atualizacao_avaliacao=parse_br_decimal(r["fator_de_atualizacao_avaliacao"]),
                margem=parse_br_decimal(r["margem"]),
                peso=parse_br_decimal(r["peso"]),
                valor_p_grama=parse_br_decimal(r["valor_p_grama"]),
                laudo=r["laudo"] or "",
            )
        )

    update_fields = [
        f.name
        for f in ContratoPenhor._meta.get_fields()
        if getattr(f, "concrete", False)
        and not f.primary_key
        and f.name not in ("criado_em",)
    ]

    with transaction.atomic():
        ContratoPenhor.objects.bulk_create(
            objs,
            batch_size=BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["contrato"],
            update_fields=update_fields,
        )
    return len(objs)