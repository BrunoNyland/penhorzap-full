"""
Import the legacy 0886.sqlite3 export (clientes, contratos, agencias_penhor,
licitacoes) into the real penhorzap MySQL database.

Usage:
    python manage.py import_sqlite /projects/penhorzap/0886.sqlite3
"""
import logging

from django.core.management.base import BaseCommand
from django.db import connection

from core.models import Cliente, Conversa, ContratoPenhor, Telefone
from core.services import importar_sqlite_arquivo
from core.utils import normalizar_cpfs_clientes

logger = logging.getLogger("core.import_sqlite")


class Command(BaseCommand):
    help = "Importa clientes, contratos, agencias_penhor e licitacoes do sqlite legado para o MySQL."

    def add_arguments(self, parser):
        parser.add_argument("sqlite_path", type=str)

    def handle(self, *args, **options):
        path = options["sqlite_path"]
        counts = importar_sqlite_arquivo(path)

        self.stdout.write(self.style.SUCCESS("Import concluído:"))
        for table, n in counts.items():
            self.stdout.write(f"  {table}: {n}")

        # O import legado (core.services.importar_sqlite_arquivo) grava o cpf
        # como veio do sqlite de origem, que pode ter pontuação/espaços
        # inconsistentes. Normaliza para 11 dígitos após cada import,
        # reaproveitando o mesmo helper usado pela migração 0014.
        resultado = normalizar_cpfs_clientes(
            connection, Cliente, Telefone, ContratoPenhor, Conversa, logger=logger,
        )
        if resultado["renomeados"]:
            self.stdout.write(
                self.style.SUCCESS(f"CPFs normalizados após import: {resultado['renomeados']}")
            )
        if resultado["colisoes"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Colisões de CPF ao normalizar: {resultado['colisoes']} "
                    "(mantidos sem alteração; ver logs)"
                )
            )