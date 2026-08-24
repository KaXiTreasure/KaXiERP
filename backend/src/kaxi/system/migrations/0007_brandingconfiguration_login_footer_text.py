from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0006_brandingconfiguration_login_card_opacity")]

    operations = [
        migrations.AddField(
            model_name="brandingconfiguration",
            name="login_footer_text",
            field=models.CharField(
                blank=True,
                default="V1.0 · 全链路追溯",
                max_length=300,
            ),
        ),
    ]
