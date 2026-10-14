import importlib

from django.db import migrations


def backfill_thumbnails(apps, schema_editor):
    # 0003 ran on production with a filter that missed the NULL thumbs every
    # existing photo had, so it created none; this runs the corrected version.
    importlib.import_module('moodboard.migrations.0003_backfill_thumbnails').backfill_thumbnails(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('moodboard', '0003_backfill_thumbnails'),
    ]

    operations = [
        migrations.RunPython(backfill_thumbnails, migrations.RunPython.noop),
    ]
