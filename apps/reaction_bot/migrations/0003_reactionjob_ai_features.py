from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reaction_bot", "0002_reactionjob_subscriptions"),
    ]

    operations = [
        migrations.AddField(
            model_name="reactionjob",
            name="ai_smart_emoji",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="reactionjob",
            name="react_to_comments",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="reactionjob",
            name="comment_reaction_probability",
            field=models.FloatField(default=0.3),
        ),
    ]
