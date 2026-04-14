"""매수 종목 선정 모듈.

1차: 최소 거래대금 + 상승 종목 필터
2차: 호가 분석 (매수세 우위 + 스프레드 제한)
3차: 거래대금 상위 5개
4차: 기술적 지표 점수로 최종 순위 결정
"""

import logging
import time
from datetime import timedelta

import pandas as pd
from django.utils import timezone

from . import upbit_client
from .indicators import calculate_rsi, calculate_macd, calculate_bollinger_bands
from .models import FailedMarket, AskRecord

logger = logging.getLogger(__name__)

# 24시간 최소 거래대금 (50억원) - 이 이하는 단타 부적합
MIN_TRADE_VALUE_24H = 5_000_000_000

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
    # 5분 지난 FailedMarket 자동 해제
    failed_cooldown = timezone.now() - timedelta(minutes=5)
    FailedMarket.objects.filter(failed_at__lte=failed_cooldown).delete()
    failed = set(FailedMarket.objects.values_list("market", flat=True))
    cooldown = timezone.now() - timedelta(minutes=10)
    recent_sold = set(
        AskRecord.objects.filter(recorded_at__gte=cooldown)
        .values_list("market", flat=True)
    )
    # USDT 등 스테이블코인 제외
    stablecoins = {"KRW-USDT", "KRW-USDC", "KRW-DAI", "KRW-TUSD"}
    excluded = failed | recent_sold | active_markets | stablecoins

    # 1차: 최소 거래대금 + 상승 종목 상위 10개
    rising = [
        t for t in tickers
        if t["market"] not in excluded
        and float(t.get("signed_change_rate", 0)) > 0
        and float(t.get("acc_trade_price_24h", 0)) >= MIN_TRADE_VALUE_24H
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

        # 매수세 우위: bid > ask × 1.2
        if total_ask <= 0 or total_bid <= total_ask * 1.2:
            continue

        # 스프레드 < 0.15%
        units = ob.get("orderbook_units", [])
        if not units:
            continue
        ask_price = float(units[0].get("ask_price", 0))
        bid_price = float(units[0].get("bid_price", 0))
        if bid_price <= 0:
            continue
        spread = ((ask_price - bid_price) / bid_price) * 100
        if spread >= 0.15:
            continue

        passed.append(t)

    if not passed:
        return None

    # 3차: 거래대금 상위 5개 중 현재가 × 거래대금 최고
    passed.sort(
        key=lambda t: float(t.get("acc_trade_price_24h", 0)), reverse=True
    )
    top5 = passed[:5]

    # 4차: 기술적 지표 점수로 최종 순위 결정
    scored = []
    for t in top5:
        market = t["market"]
        base_score = float(t.get("trade_price", 0)) * float(t.get("acc_trade_price_24h", 0))
        indicator_score, blocked = _score_indicators(market)

        if blocked:
            logger.info("%s 매수 제외: 극단적 과매수", market)
            continue

        scored.append((t, base_score, indicator_score))

    if not scored:
        # 지표로 전부 차단된 경우, 거래대금 기준 최상위 선정 (매매 기회 보존)
        best = top5[0]
        logger.info("종목 선정: %s (지표 전부 차단, 거래대금 기준)", best["market"])
        return best["market"]

    # 지표 점수 반영하여 최종 선정
    scored.sort(key=lambda x: x[2], reverse=True)
    best = scored[0][0]
    logger.info("종목 선정: %s (지표점수=%.1f)", best["market"], scored[0][2])
    return best["market"]


def _score_indicators(market: str) -> tuple[float, bool]:
    """기술적 지표 점수 계산.

    Returns:
        (점수, 차단 여부) - 점수가 높을수록 매수 적합
        차단은 RSI > 80 + BB 상단 돌파인 극단적 과매수만 해당
    """
    candles = upbit_client.get_candles_minutes(market, unit=3, count=50)
    if not candles or len(candles) < 26:
        return 0.0, False  # 데이터 부족 시 중립 점수

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

        score = 0.0

        # RSI 점수: 30~50이 가장 좋은 진입 구간
        if rsi < 30:
            score += 2  # 과매도 = 반등 기대
        elif rsi < 50:
            score += 3  # 최적 진입 구간
        elif rsi < 65:
            score += 1  # 양호
        elif rsi < 80:
            score -= 1  # 주의
        else:
            score -= 3  # 과매수

        # MACD 점수
        if macd["histogram"] > 0:
            score += 2  # 상승 모멘텀
        else:
            score -= 1  # 하락 모멘텀

        # 볼린저밴드 위치 점수
        if current_price < bb["lower"]:
            score += 2  # 하단 이탈 = 반등 기대
        elif current_price < bb["middle"]:
            score += 1  # 중간 이하 = 상승 여력
        elif current_price > bb["upper"]:
            score -= 2  # 상단 돌파 = 과열

        # 극단적 과매수만 차단: RSI 80 이상 + 볼린저 상단 돌파
        blocked = rsi > 80 and current_price > bb["upper"]

        logger.info(
            "%s 지표: RSI=%.1f MACD_H=%.4f BB위치=%s → 점수=%.1f",
            market, rsi, macd["histogram"],
            "상단↑" if current_price > bb["upper"] else
            "중간↑" if current_price > bb["middle"] else "하단↓",
            score,
        )
        return score, blocked
    except Exception as e:
        logger.warning("%s 지표 계산 실패: %s", market, e)
        return 0.0, False
