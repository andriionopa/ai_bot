from celery import shared_task

from apps.comment_parser.models import CommentParserJob
from apps.comment_parser.services import run_parser_job


@shared_task
def run_comment_parser_job_task(job_id: int) -> dict[str, object]:
    job = CommentParserJob.objects.filter(pk=job_id).first()
    if not job:
        return {"job_id": job_id, "status": "deleted"}
    job = run_parser_job(job_id)
    return {"job_id": job.id, "status": job.status}
