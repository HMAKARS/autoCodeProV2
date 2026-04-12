"""매수 종목 선정 모듈.

1차: 상승률 상위 10개
2차: 호가 분석 (매수세 우위 + 스프레드 제한)
3차: 거래대금 × 현재가 최종 1개 선정
"""

import logging
import time

from . import upbit_client
from .models import FailedMarket, AskRecord

logger = logging.getLogger(__name__)

# 호가 캐시 (5초)
_orderbook_cache: dict = {}
_orderbook_cache_time: float = 0.0
CACHE_TTL = 5


def _get_orderbook_cached(markets: list[str]) -> list[dict]:
    """호가 데이터 캐시 조회."""
    global _orderbook_cache, _orderbook_cache_time
    now = time.time()
    key = ",".join(sorted(markets))
    if key in _orderbook_cache and (now - _orderbook_cache_time) < CACHE_TTL:
        return _orderbook_cache[key]

    data = upbit_client.get_orderbook(markets)
    if data:
        _orderbook_cache[key] = data
        _orderbook_cache_time = now
    return data or []


def select_coin(tickers: list[dict], active_markets: set[str]) -> str | None:
    """매수 종목 선정. 3단계 필터링.

    Args:
        tickers: 전체 코인 시세 리스트
        active_markets: 현재 보유 중인 종목 집합

    Returns:
        최종 선정된 마켓 코드 또는 None
    """
    # 제외 목록 구성
    failed = set(FailedMarket.objects.values_list("market", flat=True))
    from django.utils import timezone
    from datetime import timedelta
    cooldown = timezone.now() - timedelta(minutes=10)
    recent_sold = set(
        AskRecord.objects.filter(recorded_at__gte=cooldown)
        .values_list("market", flat=True)
    )
    excluded = failed | recent_sold | active_markets

    # 1차: 상승 종목 상위 10개
    rising = [
        t for t in tickers
        if t["market"] not in excluded
        and float(t.get("signed_change_rate", 0)) > 0
    ]
    rising.sort(key=lambda t: float(t.get("signed_change_rate", 0)), reverse=True)
    top10 = rising[:10]

    if not top10:
        return None

    # 2차: 호가 분석
    markets_to_check = [t["market"] for t in top10]
    orderbooks = _get_orderbook_cached(markets_to_check)
    ob_map = {ob["market"]: ob for ob in orderbooks}

    passed = []
    for t in top10:
        ob = ob_map.get(t["market"])
        if not ob:
            continue

        total_bid = float(ob.get("total_bid_size", 0))
        total_ask = float(ob.get("total_ask_size", 0))

        # 매수세 우위: bid > ask × 1.5
        if total_ask <= 0 or total_bid <= total_ask * 1.5:
            continue

        # 스프레드 < 0.1%
        units = ob.get("orderbook_units", [])
        if not units:
            continue
        ask_price = float(units[0].get("ask_price", 0))
        bid_price = float(units[0].get("bid_price", 0))
        if bid_price <= 0:
            continue
        spread = ((ask_price - bid_price) / bid_price) * 100
        if spread >= 0.1:
            continue

        passed.append(t)

    if not passed:
        return None

    # 3차: 거래대금 상위 5개 중 현재가 × 거래대금 최고
    passed.sort(
        key=lambda t: float(t.get("acc_trade_price_24h", 0)), reverse=True
    )
    top5 = passed[:5]

    best = max(
        top5,
        key=lambda t: float(t.get("trade_price", 0)) * float(t.get("acc_trade_price_24h", 0)),
    )
    logger.info("종목 선정: %s", best["market"])
    return best["market"]
