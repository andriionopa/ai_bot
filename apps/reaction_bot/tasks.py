from celery import shared_task

from apps.reaction_bot.models import ReactionJob
from apps.reaction_bot.services import run_reaction_job


@shared_task
def run_reaction_job_task(job_id: int) -> dict:
    job = ReactionJob.objects.filter(pk=job_id).first()
    if not job:
        return {"job_id": job_id, "status": "deleted"}
    job = run_reaction_job(job_id)
    return {"job_id": job.id, "status": job.status}
