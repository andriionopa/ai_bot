# Generated manually for warmup queue cleanup.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("warmup", "0002_warmup_full_scenarios_and_logs"),
    ]

    operations = [
        migrations.AddField(
            model_name="warmupaction",
            name="celery_task_id",
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
