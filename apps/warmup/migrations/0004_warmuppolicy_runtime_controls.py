from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warmup", "0003_warmupaction_celery_task_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="warmuppolicy",
            name="actions_per_day",
            field=models.PositiveSmallIntegerField(default=100),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="actions_per_hour",
            field=models.PositiveSmallIntegerField(default=15),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="auto_adapt_limits",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="messages_per_day",
            field=models.PositiveSmallIntegerField(default=12),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="progressive_ramp",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="random_breaks",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="session_duration_minutes",
            field=models.PositiveIntegerField(default=30),
        ),
    ]
