"""매수 종목 선정 모듈.

1차: 상승률 상위 10개
2차: 호가 분석 (매수세 우위 + 스프레드 제한)
3차: 거래대금 × 현재가 최종 1개 선정
4차: 기술적 지표 검증 (RSI, MACD, 볼린저밴드)
"""

import logging
import time

import pandas as pd

from . import upbit_client
from .indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands
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

    # 거래대금 × 현재가 기준 정렬
    top5.sort(
        key=lambda t: float(t.get("trade_price", 0)) * float(t.get("acc_trade_price_24h", 0)),
        reverse=True,
    )

    # 4차: 기술적 지표 검증 (상위 후보부터 순서대로 확인)
    for candidate in top5:
        market = candidate["market"]
        if _check_indicators(market):
            logger.info("종목 선정: %s (지표 통과)", market)
            return market

    # 지표 통과 종목이 없으면 최상위 후보 선정 (기존 로직 유지)
    best = top5[0]
    logger.info("종목 선정: %s (지표 미통과, 거래대금 기준)", best["market"])
    return best["market"]


def _check_indicators(market: str) -> bool:
    """기술적 지표로 매수 적합성 검증.

    - RSI < 70: 과매수 구간이 아닌지 확인
    - MACD histogram > 0: 상승 모멘텀 확인
    - 현재가가 볼린저밴드 상단 미만: 과열 구간이 아닌지 확인
    """
    candles = upbit_client.get_candles_minutes(market, unit=3, count=50)
    if not candles or len(candles) < 26:
        return True  # 데이터 부족 시 통과 (기존 로직대로)

    # 캔들 데이터를 DataFrame 변환 (오래된 순으로 정렬)
    df = pd.DataFrame(candles[::-1])
    df = df.rename(columns={
        "opening_price": "open",
        "high_price": "high",
        "low_price": "low",
        "trade_price": "close",
        "candle_acc_trade_volume": "volume",
    })

    try:
        rsi = calculate_rsi(df)
        macd = calculate_macd(df)
        bb = calculate_bollinger_bands(df)
        current_price = float(df["close"].iloc[-1])

        # 과매수 구간(RSI > 70)이면서 볼린저 상단 돌파 → 매수 부적합
        if rsi > 70 and current_price > bb["upper"]:
            logger.info("%s 매수 제외: RSI=%.1f, 볼린저 상단 돌파", market, rsi)
            return False

        # MACD 하락 모멘텀(histogram < 0)이면서 RSI도 높음 → 매수 부적합
        if macd["histogram"] < 0 and rsi > 65:
            logger.info(
                "%s 매수 제외: MACD histogram=%.4f, RSI=%.1f", market, macd["histogram"], rsi
            )
            return False

        return True
    except Exception as e:
        logger.warning("%s 지표 계산 실패: %s", market, e)
        return True  # 계산 실패 시 통과
