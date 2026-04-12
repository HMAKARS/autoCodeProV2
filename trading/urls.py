from django.urls import path
from . import views

urlpatterns = [
    # 대시보드
    path("", views.dashboard, name="dashboard"),

    # 자동매매 제어
    path("auto_trade/start/", views.start_auto_trade, name="auto_trade_start"),
    path("auto_trade/stop/", views.stop_auto_trade, name="auto_trade_stop"),

    # API
    path("api/fetch_account_data/", views.fetch_account_data, name="fetch_account"),
    path("api/fetch_coin_data/", views.fetch_coin_data, name="fetch_coin"),
    path("api/trade_logs/", views.trade_logs, name="trade_logs"),
    path("api/check_auto_trading/", views.check_auto_trading, name="check_auto"),
    path("api/get_market_volume/", views.get_market_volume, name="market_volume"),
    path("api/getRecntTradeLog/", views.get_recent_trade_log, name="recent_trade"),
    path("api/recentProfitLog/", views.recent_profit_log, name="recent_profit"),
]
