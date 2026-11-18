from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_change")]
    operations = [
        migrations.AddField(
            model_name="change", name="rolled_back_by", field=models.CharField(blank=True, default="", max_length=80)
        ),
        migrations.AddField(
            model_name="change", name="rolled_back_at", field=models.DateTimeField(blank=True, null=True)
        ),
    ]
