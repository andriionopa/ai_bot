# Generated manually for Stage 4 warmup scenarios.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


ACTION_CHOICES = [
    ("join_channel", "Join Channel"),
    ("join_folder", "Join Folder"),
    ("view_dialogs", "View Dialogs"),
    ("channel_scroll", "Channel Scroll"),
    ("read", "Read"),
    ("mark_read", "Mark Read"),
    ("message_search", "Message Search"),
    ("reaction", "Reaction"),
    ("forward_message", "Forward Message"),
    ("saved_note", "Saved Note"),
    ("poll_scan", "Poll Scan"),
    ("video_scan", "Video Scan"),
    ("voice_scan", "Voice Scan"),
    ("gif_search", "GIF Search"),
    ("sticker_scan", "Sticker Scan"),
    ("inline_bot_check", "Inline Bot Check"),
    ("link_preview", "Link Preview"),
    ("typing_simulation", "Typing Simulation"),
    ("profile_view", "Profile View"),
    ("settings_check", "Settings Check"),
    ("gradual_profile_check", "Gradual Profile Check"),
    ("emoji_status_check", "Emoji Status Check"),
    ("drafts_check", "Drafts Check"),
    ("notification_check", "Notification Check"),
    ("scheduled_message_check", "Scheduled Message Check"),
    ("archive_check", "Archive Check"),
    ("mute_check", "Mute Check"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("warmup", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField("warmuppolicy", "enable_view_dialogs", models.BooleanField(default=True)),
        migrations.AddField("warmuppolicy", "enable_channel_scroll", models.BooleanField(default=True)),
        migrations.AddField("warmuppolicy", "enable_mark_read", models.BooleanField(default=True)),
        migrations.AddField("warmuppolicy", "enable_message_search", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_forward_messages", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_saved_notes", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_poll_scan", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_video_scan", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_voice_scan", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_gif_search", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_sticker_scan", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_inline_bot_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_link_preview", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_typing_simulation", models.BooleanField(default=True)),
        migrations.AddField("warmuppolicy", "enable_profile_view", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_settings_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_gradual_profile_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_emoji_status_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_drafts_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_notification_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_scheduled_message_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_archive_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "enable_mute_check", models.BooleanField(default=False)),
        migrations.AddField("warmuppolicy", "search_query", models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField("warmuppolicy", "inline_bot_username", models.CharField(blank=True, default="gif", max_length=64)),
        migrations.AlterField(
            model_name="warmupaction",
            name="action_type",
            field=models.CharField(choices=ACTION_CHOICES, max_length=32),
        ),
        migrations.CreateModel(
            name="WarmupLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.CharField(choices=[("info", "Info"), ("success", "Success"), ("warning", "Warning"), ("error", "Error")], default="info", max_length=16)),
                ("message", models.CharField(max_length=500)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="warmup_logs", to="telegram_accounts.telegramaccount")),
                ("action", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="logs", to="warmup.warmupaction")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="warmup_logs", to=settings.AUTH_USER_MODEL)),
                ("plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="logs", to="warmup.warmupplan")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["owner", "created_at"], name="warmup_warm_owner_i_6b7434_idx"),
                    models.Index(fields=["account", "created_at"], name="warmup_warm_account_3474fc_idx"),
                    models.Index(fields=["plan", "created_at"], name="warmup_warm_plan_id_f7cf5d_idx"),
                ],
            },
        ),
    ]
