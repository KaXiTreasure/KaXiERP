from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0009_brandingconfiguration_login_footer_links")]

    operations = [
        migrations.AddField(model_name="brandingconfiguration", name="background_source", field=models.CharField(choices=[("local", "本地上传"), ("bing", "Bing 每日图片")], default="local", max_length=16)),
        migrations.AddField(model_name="brandingconfiguration", name="bing_image_title", field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name="brandingconfiguration", name="bing_image_copyright", field=models.CharField(blank=True, max_length=1000)),
        migrations.AddField(model_name="brandingconfiguration", name="bing_image_date", field=models.CharField(blank=True, max_length=8)),
        migrations.AddField(model_name="brandingconfiguration", name="bing_last_synced_at", field=models.DateTimeField(blank=True, null=True)),
    ]
