import uuid
from django.db import migrations, models


def populate_report_uid(apps, schema_editor):
    Report = apps.get_model("reports", "Report")
    for report in Report.objects.filter(uid__isnull=True):
        report.uid = uuid.uuid4()
        report.save(update_fields=["uid"])


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0002_alter_report_options_alter_report_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="report",
            name="uid",
            field=models.UUIDField(null=True, blank=True),
        ),
        migrations.RunPython(populate_report_uid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="report",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True),
        ),
    ]
