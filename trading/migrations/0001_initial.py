from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TradeRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("market", models.CharField(max_length=20, unique=True)),
                ("buy_price", models.FloatField()),
                ("highest_price", models.FloatField(default=0)),
                ("uuid", models.CharField(blank=True, max_length=100, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_active", models.BooleanField(default=True)),
                ("buy_krw_price", models.FloatField(default=0)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="FailedMarket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("market", models.CharField(max_length=20, unique=True)),
                ("failed_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="MarketVolumeRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("total_market_volume", models.FloatField()),
            ],
            options={
                "ordering": ["-recorded_at"],
            },
        ),
        migrations.CreateModel(
            name="AskRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("market", models.CharField(max_length=20, unique=True)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
