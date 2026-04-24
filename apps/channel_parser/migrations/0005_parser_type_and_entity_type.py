from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("channel_parser", "0004_channelcollectiontemplate_channelcollectionitem"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelparserjob",
            name="parse_type",
            field=models.CharField(choices=[("channels", "Channels"), ("groups", "Groups")], default="channels", max_length=16),
        ),
        migrations.AddField(
            model_name="channelparsertemplate",
            name="parse_type",
            field=models.CharField(choices=[("channels", "Channels"), ("groups", "Groups")], default="channels", max_length=16),
        ),
        migrations.AddField(
            model_name="parsedchannel",
            name="entity_type",
            field=models.CharField(choices=[("channel", "Channel"), ("group", "Group")], default="channel", max_length=16),
        ),
        migrations.AddField(
            model_name="channelcollectionitem",
            name="entity_type",
            field=models.CharField(choices=[("channel", "Channel"), ("group", "Group")], default="channel", max_length=16),
        ),
    ]
