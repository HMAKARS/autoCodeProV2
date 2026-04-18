from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="traderecord",
            name="stop_loss_price",
            field=models.FloatField(default=0),
        ),
    ]
