from django.utils import timezone

from core.models import ImportDataJob
from core.services import importar_sqlite_arquivo


def run_import_job(job_id: int) -> None:
    job = ImportDataJob.objects.get(pk=job_id)
    job.status = ImportDataJob.Status.RUNNING
    job.save(update_fields=["status"])
    try:
        counts = importar_sqlite_arquivo(job.arquivo.path)
        job.counts = counts
        job.status = ImportDataJob.Status.SUCCESS
        job.erro = ""
    except Exception as exc:
        job.status = ImportDataJob.Status.FAILED
        job.erro = str(exc)
        job.counts = {}
    finally:
        job.finalizado_em = timezone.now()
        job.save(update_fields=["status", "counts", "erro", "finalizado_em"])