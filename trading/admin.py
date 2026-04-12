from django.contrib import admin
from .models import TradeRecord, FailedMarket, MarketVolumeRecord, AskRecord

admin.site.register(TradeRecord)
admin.site.register(FailedMarket)
admin.site.register(MarketVolumeRecord)
admin.site.register(AskRecord)
