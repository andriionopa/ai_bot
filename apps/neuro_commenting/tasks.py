from celery import shared_task

from apps.neuro_commenting.models import NeuroCommentJob
from apps.neuro_commenting.services import run_neuro_comment_job


@shared_task
def run_neuro_comment_job_task(job_id: int) -> dict:
    job = NeuroCommentJob.objects.filter(pk=job_id).first()
    if not job:
        return {"job_id": job_id, "status": "deleted"}
    job = run_neuro_comment_job(job_id)
    return {"job_id": job.id, "status": job.status}
