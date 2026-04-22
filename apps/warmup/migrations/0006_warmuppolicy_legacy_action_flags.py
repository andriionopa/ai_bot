from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("warmup", "0005_rename_warmup_warm_owner_i_6b7434_idx_warmup_warm_owner_i_e3570e_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="warmuppolicy",
            name="enable_account_dialogs",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="enable_join_groups",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="enable_reactions",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="enable_read_channels",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="enable_story_view",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="warmuppolicy",
            name="enable_trust_boost",
            field=models.BooleanField(default=False),
        ),
    ]
