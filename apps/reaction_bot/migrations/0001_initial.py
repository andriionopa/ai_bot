from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("telegram_accounts", "0008_remove_telegramaccount_avatar"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountChannelBinding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("channel_username", models.CharField(max_length=255)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_bindings", to="telegram_accounts.telegramaccount")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="account_channel_bindings", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["owner", "account"], name="reaction_bo_owner_id_idx")],
                "unique_together": {("owner", "account", "channel_username")},
            },
        ),
        migrations.CreateModel(
            name="ReactionJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("sources", models.JSONField(blank=True, default=list)),
                ("emojis", models.JSONField(blank=True, default=list)),
                ("emoji_mode", models.CharField(choices=[("random", "Random"), ("sequential", "Sequential")], default="random", max_length=16)),
                ("reaction_probability", models.FloatField(default=1.0)),
                ("work_mode", models.CharField(choices=[("monitoring", "Monitoring"), ("existing", "Existing")], default="existing", max_length=16)),
                ("post_limit", models.PositiveIntegerField(default=20)),
                ("max_reactions", models.PositiveIntegerField(default=0)),
                ("duration_minutes", models.PositiveIntegerField(default=60)),
                ("reaction_delay_min", models.FloatField(default=3.0)),
                ("reaction_delay_max", models.FloatField(default=10.0)),
                ("entry_delay_min", models.FloatField(default=0.0)),
                ("entry_delay_max", models.FloatField(default=5.0)),
                ("ai_protection", models.BooleanField(default=True)),
                ("speed_mode", models.CharField(choices=[("safe", "Safe"), ("balanced", "Balanced"), ("fast", "Fast")], default="balanced", max_length=16)),
                ("use_channel_identity", models.BooleanField(default=False)),
                ("account_rotation", models.BooleanField(default=True)),
                ("reactions_sent", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("stopped", "Stopped")], default="draft", max_length=16)),
                ("celery_task_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("error", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accounts", models.ManyToManyField(blank=True, related_name="reaction_jobs", to="telegram_accounts.telegramaccount")),
                ("channel_bindings", models.ManyToManyField(blank=True, related_name="reaction_jobs", to="reaction_bot.accountchannelbinding")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reaction_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["owner", "status", "created_at"], name="reaction_bo_owner_id_status_idx")],
            },
        ),
        migrations.CreateModel(
            name="ReactionLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.CharField(choices=[("info", "Info"), ("success", "Success"), ("warning", "Warning"), ("error", "Error"), ("debug", "Debug")], default="info", max_length=16)),
                ("message", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reaction_logs", to="telegram_accounts.telegramaccount")),
                ("job", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="logs", to="reaction_bot.reactionjob")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reaction_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("created_at",),
                "indexes": [
                    models.Index(fields=["owner", "created_at"], name="reaction_bo_owner_created_idx"),
                    models.Index(fields=["job", "created_at"], name="reaction_bo_job_created_idx"),
                    models.Index(fields=["level"], name="reaction_bo_level_idx"),
                ],
            },
        ),
    ]
