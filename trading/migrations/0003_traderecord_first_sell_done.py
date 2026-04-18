from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trading", "0002_traderecord_stop_loss_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="traderecord",
            name="first_sell_done",
            field=models.BooleanField(default=False),
        ),
    ]
