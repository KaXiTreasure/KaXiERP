from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0007_brandingconfiguration_login_footer_text")]

    operations = [
        migrations.AddField(model_name="brandingconfiguration", name="login_slogan", field=models.CharField(blank=True, default="Slogan", max_length=120)),
        migrations.AddField(model_name="brandingconfiguration", name="login_slogan_1", field=models.CharField(blank=True, default="Slogan1", max_length=120)),
        migrations.AddField(model_name="brandingconfiguration", name="login_slogan_2", field=models.CharField(blank=True, default="Slogan2", max_length=500)),
    ]
