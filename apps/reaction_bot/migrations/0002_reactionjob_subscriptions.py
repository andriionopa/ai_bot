from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reaction_bot", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="reactionjob",
            name="use_subscriptions",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="reactionjob",
            name="subscriptions_limit",
            field=models.PositiveIntegerField(default=50),
        ),
    ]
