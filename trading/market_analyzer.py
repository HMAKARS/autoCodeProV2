"""시장 강도 분석 모듈.

BTC/ETH 변동률, 전체 거래량 변화, 상승/하락 비율
3가지 지표를 결합하여 시장 상태(bullish/bearish/neutral)를 판단한다.
"""

import logging
from django.utils import timezone
from datetime import timedelta

from . import upbit_client
from .models import MarketVolumeRecord

logger = logging.getLogger(__name__)


def _analyze_btc_eth(tickers: list[dict]) -> str:
    """BTC/ETH 변동률 기반 분석."""
    rates = []
    for t in tickers:
        if t["market"] in ("KRW-BTC", "KRW-ETH"):
            rates.append(float(t.get("signed_change_rate", 0)) * 100)

    if len(rates) < 2:
        return "neutral"

    avg = sum(rates) / len(rates)
    if avg > 2:
        return "bullish"
    elif avg < -2:
        return "bearish"
    return "neutral"


def _analyze_volume(tickers: list[dict]) -> str:
    """전체 시장 거래량 변화 기반 분석."""
    current_total = sum(float(t.get("acc_trade_price_24h", 0)) for t in tickers)

    # 이전 거래량 기록 조회 (24시간 전)
    cutoff = timezone.now() - timedelta(hours=24)
    prev_record = (
        MarketVolumeRecord.objects
        .filter(recorded_at__lte=cutoff)
        .order_by("-recorded_at")
        .first()
    )

    # 현재 거래량 기록 저장 (가장 최근 기록과 1시간 이상 차이나면)
    latest = MarketVolumeRecord.objects.order_by("-recorded_at").first()
    if not latest or (timezone.now() - latest.recorded_at).total_seconds() > 3600:
        MarketVolumeRecord.objects.create(total_market_volume=current_total)

    if not prev_record or prev_record.total_market_volume == 0:
        return "neutral"

    change_rate = (
        (current_total - prev_record.total_market_volume)
        / prev_record.total_market_volume
        * 100
    )
    if change_rate > 20:
        return "bullish"
    elif change_rate < -20:
        return "bearish"
    return "neutral"


def _analyze_up_down_ratio(tickers: list[dict]) -> str:
    """상승/하락 코인 비율 분석."""
    if not tickers:
        return "neutral"

    up = sum(1 for t in tickers if float(t.get("signed_change_rate", 0)) > 0)
    total = len(tickers)
    ratio = up / total

    if ratio > 0.6:
        return "bullish"
    elif ratio < 0.4:
        return "bearish"
    return "neutral"


def get_market_state() -> str:
    """시장 상태 통합 판단.

    3가지 지표 중 2개 이상이 동일 방향이면 해당 방향으로 결정.
    Returns: "bullish", "bearish", "neutral"
    """
    markets = upbit_client.get_krw_markets()
    tickers = upbit_client.get_ticker(markets)
    if not tickers:
        return "neutral"

    signals = [
        _analyze_btc_eth(tickers),
        _analyze_volume(tickers),
        _analyze_up_down_ratio(tickers),
    ]

    bullish_count = signals.count("bullish")
    bearish_count = signals.count("bearish")

    if bullish_count >= 2:
        return "bullish"
    elif bearish_count >= 2:
        return "bearish"
    return "neutral"
