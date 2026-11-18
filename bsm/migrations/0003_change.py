from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("bsm", "0002_remove_change")]
    operations = [
        migrations.CreateModel(
            name="Change",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("op", models.CharField(max_length=40)),
                ("action", models.CharField(max_length=16)),
                ("target", models.CharField(db_index=True, max_length=240)),
                ("before", models.JSONField(blank=True, null=True)),
                ("after", models.JSONField(blank=True, null=True)),
                ("status", models.CharField(db_index=True, default="applied", max_length=16)),
                ("actor", models.CharField(max_length=80)),
                ("applied_by", models.CharField(blank=True, default="", max_length=80)),
                ("restores_id", models.BigIntegerField(blank=True, null=True)),
                ("digest", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-id"]},
        )
    ]
