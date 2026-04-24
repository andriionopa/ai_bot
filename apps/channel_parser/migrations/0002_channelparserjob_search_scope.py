from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("channel_parser", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelparserjob",
            name="search_scope",
            field=models.CharField(
                choices=[("global", "Global"), ("subscriptions", "Subscriptions"), ("both", "Both")],
                default="both",
                max_length=16,
            ),
        ),
    ]
