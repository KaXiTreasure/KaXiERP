from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0008_brandingconfiguration_login_slogans")]

    operations = [
        migrations.AddField(
            model_name="brandingconfiguration",
            name="login_footer_links",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
