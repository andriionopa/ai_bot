from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("channel_parser", "0003_channelparsertemplate"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelCollectionTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_collection_templates", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="ChannelCollectionItem",
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
                ("matched_query", models.CharField(blank=True, max_length=255)),
                ("description", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_collection_items", to=settings.AUTH_USER_MODEL)),
                ("source_job", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="template_items", to="channel_parser.channelparserjob")),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="channel_parser.channelcollectiontemplate")),
            ],
        ),
        migrations.AddIndex(
            model_name="channelcollectiontemplate",
            index=models.Index(fields=["owner", "name"], name="channel_col_owner_i_e290ef_idx"),
        ),
        migrations.AddIndex(
            model_name="channelcollectiontemplate",
            index=models.Index(fields=["owner", "created_at"], name="channel_col_owner_i_37ee19_idx"),
        ),
        migrations.AddConstraint(
            model_name="channelcollectiontemplate",
            constraint=models.UniqueConstraint(fields=("owner", "name"), name="channel_collection_template_owner_name_uniq"),
        ),
        migrations.AddIndex(
            model_name="channelcollectionitem",
            index=models.Index(fields=["owner", "created_at"], name="channel_col_owner_i_a0b5a9_idx"),
        ),
        migrations.AddIndex(
            model_name="channelcollectionitem",
            index=models.Index(fields=["template", "created_at"], name="channel_col_templat_eb0ca5_idx"),
        ),
        migrations.AddIndex(
            model_name="channelcollectionitem",
            index=models.Index(fields=["template", "username"], name="channel_col_templat_1a4e6f_idx"),
        ),
        migrations.AddIndex(
            model_name="channelcollectionitem",
            index=models.Index(fields=["template", "telegram_id"], name="channel_col_templat_7136f5_idx"),
        ),
    ]
