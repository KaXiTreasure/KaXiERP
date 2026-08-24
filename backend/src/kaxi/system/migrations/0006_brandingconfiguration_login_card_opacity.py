from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("system", "0005_fontasset_brandingconfiguration_primary_font_and_more")]

    operations = [
        migrations.AddField(
            model_name="brandingconfiguration",
            name="login_card_opacity",
            field=models.PositiveSmallIntegerField(default=92),
        ),
    ]
