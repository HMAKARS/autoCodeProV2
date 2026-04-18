from django.db import models


class TradeRecord(models.Model):
    """거래 기록."""
    market = models.CharField(max_length=20, unique=True)
    buy_price = models.FloatField()
    highest_price = models.FloatField(default=0)
    stop_loss_price = models.FloatField(default=0)
    uuid = models.CharField(max_length=100, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    buy_krw_price = models.FloatField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        status = "활성" if self.is_active else "비활성"
        return f"[{status}] {self.market} @ {self.buy_price:,.0f}"


class FailedMarket(models.Model):
    """주문 실패 종목."""
    market = models.CharField(max_length=20, unique=True)
    failed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.market} ({self.failed_at})"


class MarketVolumeRecord(models.Model):
    """시장 거래량 기록."""
    recorded_at = models.DateTimeField(auto_now_add=True)
    total_market_volume = models.FloatField()

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.recorded_at} - {self.total_market_volume:,.0f}"


class AskRecord(models.Model):
    """매도 기록 (재매수 제한용)."""
    market = models.CharField(max_length=20, unique=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.market} ({self.recorded_at})"
