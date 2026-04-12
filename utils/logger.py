import csv
import os
import logging
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
TRADE_LOG_FILE = os.path.join(LOG_DIR, "trades.csv")

# 콘솔 로거 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scalping_bot")

TRADE_HEADERS = [
    "timestamp",
    "action",       # BUY / SELL
    "market",
    "price",
    "amount",       # KRW 금액 (매수) 또는 수량 (매도)
    "score",        # 시그널 점수
    "reason",       # 매매 사유
    "pnl",          # 손익 (매도 시)
    "pnl_pct",      # 손익률 (매도 시)
]


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _ensure_csv_header():
    _ensure_log_dir()
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(TRADE_HEADERS)


def log_trade(
    action: str,
    market: str,
    price: float,
    amount: float,
    score: int = 0,
    reason: str = "",
    pnl: float = 0.0,
    pnl_pct: float = 0.0,
):
    """거래 내역을 CSV에 기록."""
    _ensure_csv_header()
    with open(TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action,
            market,
            price,
            amount,
            score,
            reason,
            pnl,
            pnl_pct,
        ])
    logger.info(
        "%s %s | price=%.2f amount=%.4f score=%d reason=%s pnl=%.0f(%.2f%%)",
        action, market, price, amount, score, reason, pnl, pnl_pct,
    )
