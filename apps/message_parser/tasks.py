from celery import shared_task

from apps.message_parser.models import MessageParserJob
from apps.message_parser.services import run_parser_job


@shared_task
def run_message_parser_job_task(job_id: int) -> dict[str, object]:
    job = MessageParserJob.objects.filter(pk=job_id).first()
    if not job:
        return {"job_id": job_id, "status": "deleted"}
    job = run_parser_job(job_id)
    return {"job_id": job.id, "status": job.status}
