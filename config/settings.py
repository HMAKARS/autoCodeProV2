import os
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    # 업비트 API
    "access_key": os.getenv("UPBIT_ACCESS_KEY", ""),
    "secret_key": os.getenv("UPBIT_SECRET_KEY", ""),

    # 코인 선정
    "market": "KRW",
    "top_n": 5,
    "min_trade_volume": 1_000_000_000,  # 최소 거래대금 10억
    "exclude_new_days": 7,
    "max_change_rate": 30,              # ±30% 초과 제외
    "max_spread_pct": 0.5,

    # 캔들/지표
    "candle_interval": 5,       # 5분봉
    "candle_count": 100,
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_period": 20,
    "volume_threshold": 1.5,

    # 매매
    "buy_amount": 500_000,      # 1회 매매금 (원)
    "max_positions": 3,
    "total_budget_ratio": 0.8,

    # 리스크
    "stop_loss_pct": -2.0,
    "take_profit_mid": True,     # 중심선 익절
    "take_profit_upper": True,   # 상단밴드 익절
    "time_stop_minutes": 30,
    "cooldown_minutes": 15,
    "max_daily_trades": 20,
    "max_daily_loss": -50_000,

    # 시스템
    "loop_interval": 5,          # 메인루프 간격 (초)
    "market_refresh_interval": 1800,  # 코인 재선정 간격 (초)
}
