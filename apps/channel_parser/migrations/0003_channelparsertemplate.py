from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("channel_parser", "0002_channelparserjob_search_scope"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelParserTemplate",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_parser_templates", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name="channelparsertemplate",
            index=models.Index(fields=["owner", "name"], name="channel_par_owner_i_814a0d_idx"),
        ),
        migrations.AddIndex(
            model_name="channelparsertemplate",
            index=models.Index(fields=["owner", "created_at"], name="channel_par_owner_i_547bb0_idx"),
        ),
    ]
