from celery import shared_task

from apps.channel_parser.models import ChannelParserJob
from apps.channel_parser.services import run_parser_job


@shared_task
def run_channel_parser_job_task(job_id: int) -> dict[str, object]:
    job = ChannelParserJob.objects.filter(pk=job_id).first()
    if not job:
        return {"job_id": job_id, "status": "deleted"}
    job = run_parser_job(job_id)
    return {"job_id": job.id, "status": job.status}
