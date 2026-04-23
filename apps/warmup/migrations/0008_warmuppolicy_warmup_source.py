from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("warmup", "0007_alter_warmupaction_action_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="warmuppolicy",
            name="warmup_source",
            field=models.CharField(
                choices=[
                    ("subscriptions", "Subscriptions"),
                    ("targets", "Targets"),
                ],
                default="subscriptions",
                max_length=16,
            ),
        ),
    ]
