from django.db import migrations


# Historical no-op. The original AddField duplicated a column already present in
# 0001_initial (search_scope was back-ported into the initial migration). Existing
# installs already have this migration recorded, so we keep its name in the graph
# but stop trying to re-add the column on fresh databases (pytest --create-db,
# postgres test_app, etc.).
class Migration(migrations.Migration):
    dependencies = [
        ("channel_parser", "0001_initial"),
    ]

    operations = []
