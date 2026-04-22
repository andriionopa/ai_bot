from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("warmup", "0006_warmuppolicy_legacy_action_flags"),
    ]

    operations = [
        migrations.AlterField(
            model_name="warmupaction",
            name="action_type",
            field=models.CharField(
                choices=[
                    ("join_channel", "Join Channel"),
                    ("join_folder", "Join Folder"),
                    ("view_dialogs", "View Dialogs"),
                    ("channel_scroll", "Channel Scroll"),
                    ("read", "Read"),
                    ("account_dialog", "Account Dialog"),
                    ("story_view", "Story View"),
                    ("trust_boost", "Trust Boost"),
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
                ],
                max_length=32,
            ),
        ),
    ]
