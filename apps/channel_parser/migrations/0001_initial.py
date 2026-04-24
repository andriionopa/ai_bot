from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("telegram_accounts", "0008_remove_telegramaccount_avatar"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelParserJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("keywords", models.JSONField(blank=True, default=list)),
                ("suffixes", models.JSONField(blank=True, default=list)),
                ("search_scope", models.CharField(choices=[("global", "Global"), ("subscriptions", "Subscriptions"), ("both", "Both")], default="both", max_length=16)),
                ("ai_protection", models.BooleanField(default=True)),
                ("fast_mode", models.BooleanField(default=False)),
                ("speed_mode", models.CharField(choices=[("safe", "Safe"), ("balanced", "Balanced"), ("fast", "Fast")], default="balanced", max_length=16)),
                ("activity_filter", models.CharField(choices=[("any", "Any"), ("active", "Active"), ("inactive", "Inactive")], default="any", max_length=16)),
                ("comments_filter", models.CharField(choices=[("any", "Any"), ("open", "Open"), ("closed", "Closed")], default="any", max_length=16)),
                ("result_limit", models.PositiveIntegerField(default=50)),
                ("subscriber_min", models.PositiveIntegerField(default=500)),
                ("subscriber_max", models.PositiveIntegerField(default=1000000)),
                ("rating_min", models.PositiveSmallIntegerField(default=5)),
                ("language_detection", models.BooleanField(default=True)),
                ("languages", models.JSONField(blank=True, default=list)),
                ("request_delay_seconds", models.FloatField(default=2.0)),
                ("channel_delay_seconds", models.FloatField(default=1.0)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("running", "Running"), ("succeeded", "Succeeded"), ("failed", "Failed"), ("stopped", "Stopped")], default="draft", max_length=16)),
                ("celery_task_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("error", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accounts", models.ManyToManyField(blank=True, related_name="channel_parser_jobs", to="telegram_accounts.telegramaccount")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_parser_jobs", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ParsedChannel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("username", models.CharField(blank=True, max_length=255)),
                ("url", models.URLField(blank=True, max_length=512)),
                ("telegram_id", models.BigIntegerField(blank=True, null=True)),
                ("subscribers", models.PositiveIntegerField(default=0)),
                ("rating", models.PositiveSmallIntegerField(default=0)),
                ("language", models.CharField(blank=True, max_length=16)),
                ("activity_level", models.CharField(blank=True, max_length=16)),
                ("comments_open", models.BooleanField(blank=True, null=True)),
                ("last_post_at", models.DateTimeField(blank=True, null=True)),
                ("matched_query", models.CharField(blank=True, max_length=255)),
                ("description", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="results", to="channel_parser.channelparserjob")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parsed_channels", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("owner", "username", "telegram_id")}},
        ),
        migrations.CreateModel(
            name="ChannelParserLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.CharField(choices=[("info", "Info"), ("success", "Success"), ("warning", "Warning"), ("error", "Error"), ("debug", "Debug")], default="info", max_length=16)),
                ("message", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="channel_parser_logs", to="telegram_accounts.telegramaccount")),
                ("job", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="logs", to="channel_parser.channelparserjob")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_parser_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.AddIndex(model_name="channelparserjob", index=models.Index(fields=["owner", "status", "created_at"], name="channel_par_owner_i_46a7ba_idx")),
        migrations.AddIndex(model_name="parsedchannel", index=models.Index(fields=["owner", "created_at"], name="channel_par_owner_i_dbb469_idx")),
        migrations.AddIndex(model_name="parsedchannel", index=models.Index(fields=["job", "rating"], name="channel_par_job_id_7a46ea_idx")),
        migrations.AddIndex(model_name="parsedchannel", index=models.Index(fields=["username"], name="channel_par_usernam_74646c_idx")),
        migrations.AddIndex(model_name="channelparserlog", index=models.Index(fields=["owner", "created_at"], name="channel_par_owner_i_b89a9d_idx")),
        migrations.AddIndex(model_name="channelparserlog", index=models.Index(fields=["job", "created_at"], name="channel_par_job_id_2d45ba_idx")),
        migrations.AddIndex(model_name="channelparserlog", index=models.Index(fields=["level"], name="channel_par_level_ddee97_idx")),
    ]
