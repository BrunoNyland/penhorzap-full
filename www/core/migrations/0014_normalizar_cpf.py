"""Normaliza Cliente.cpf (PK) existentes para 11 dígitos, sem pontuação.

Não é uma migração de schema: usa SQL bruto (via core.utils.normalizar_cpfs_clientes)
para renomear a chave primária de Cliente e as FKs de Telefone/ContratoPenhor/
Conversa em cascata, com checagem de FK temporariamente desligada. `Model.save()`
não serve para isso porque alterar o valor da PK gera um INSERT (linha nova),
não um UPDATE — deixaria as FKs das linhas filhas apontando para um cpf que
deixou de existir.

atomic=False: em SQLite, `PRAGMA foreign_keys` só pode ser alterado fora de
uma transação em aberto.
"""
import logging

from django.db import migrations

logger = logging.getLogger("core.migrations.0014_normalizar_cpf")


def normalizar_cpfs(apps, schema_editor):
    from core.utils import normalizar_cpfs_clientes

    Cliente = apps.get_model("core", "Cliente")
    Telefone = apps.get_model("core", "Telefone")
    ContratoPenhor = apps.get_model("core", "ContratoPenhor")
    Conversa = apps.get_model("core", "Conversa")

    resultado = normalizar_cpfs_clientes(
        schema_editor.connection,
        Cliente,
        Telefone,
        ContratoPenhor,
        Conversa,
        logger=logger,
    )
    if resultado["renomeados"]:
        logger.info("normalizar_cpf: %s cliente(s) renomeado(s) para cpf normalizado.", resultado["renomeados"])
    if resultado["colisoes"]:
        logger.warning(
            "normalizar_cpf: %s cliente(s) com cpf mantido sem alteração por colisão (ver warnings acima).",
            resultado["colisoes"],
        )


def noop_reverse(apps, schema_editor):
    """Irreversível por natureza (perderíamos a pontuação original); no-op."""


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("core", "0013_alter_mensagensconfig_system_prompt"),
    ]

    operations = [
        migrations.RunPython(normalizar_cpfs, noop_reverse),
    ]
