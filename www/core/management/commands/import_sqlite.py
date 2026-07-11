"""
Import the legacy 0886.sqlite3 export (clientes, contratos, agencias_penhor,
licitacoes) into the real penhorzap MySQL database.

Usage:
    python manage.py import_sqlite /projects/penhorzap/0886.sqlite3
"""
from django.core.management.base import BaseCommand

from core.services import importar_sqlite_arquivo


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