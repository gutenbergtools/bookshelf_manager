from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_remove_change_digest"),
    ]

    operations = [
        migrations.RenameModel(old_name="AuditEvent", new_name="EventLog"),
        migrations.RemoveField(model_name="eventlog", name="kind"),
        migrations.AlterModelOptions(
            name="eventlog",
            options={
                "ordering": ["-id"],
                "verbose_name": "event log entry",
                "verbose_name_plural": "event log",
            },
        ),
    ]
