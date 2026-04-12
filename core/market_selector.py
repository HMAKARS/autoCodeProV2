import time
from utils.upbit_client import UpbitClient
from utils.logger import logger
from config.settings import CONFIG


class MarketSelector:
    """거래량 상위 코인 선정 모듈.

    KRW 마켓에서 거래대금 상위 N개를 선정하고,
    신규 상장/과도한 변동성/유동성 부족 코인을 제외한다.
    """

    def __init__(self, client: UpbitClient):
        self.client = client
        self._cached_targets: list[str] = []
        self._last_refresh: float = 0.0

    def get_top_volume_coins(self, force_refresh: bool = False) -> list[str]:
        """거래대금 상위 코인 목록 반환.

        캐시 유효시간(market_refresh_interval) 내에는 캐시된 결과를 반환한다.
        """
        now = time.time()
        interval = CONFIG["market_refresh_interval"]

        if not force_refresh and self._cached_targets:
            if now - self._last_refresh < interval:
                return self._cached_targets

        targets = self._select_coins()
        if targets:
            self._cached_targets = targets
            self._last_refresh = now
            logger.info("코인 선정 갱신: %s", targets)

        return self._cached_targets

    def _select_coins(self) -> list[str]:
        """실제 코인 선정 로직."""
        markets = self.client.get_krw_markets()
        if not markets:
            logger.warning("KRW 마켓 목록 조회 실패")
            return []

        # 상세 티커 정보 조회
        ticker_data = self.client.get_tickers_detail(markets)
        if not ticker_data:
            logger.warning("티커 상세 정보 조회 실패")
            return []

        candidates = []
        for t in ticker_data:
            market = t.get("market", "")
            if not market.startswith("KRW-"):
                continue

            acc_trade_price_24h = float(t.get("acc_trade_price_24h", 0))
            signed_change_rate = abs(float(t.get("signed_change_rate", 0)) * 100)

            # 최소 거래대금 필터
            if acc_trade_price_24h < CONFIG["min_trade_volume"]:
                continue

            # 과도한 변동률 제외
            if signed_change_rate > CONFIG["max_change_rate"]:
                continue

            candidates.append({
                "market": market,
                "trade_volume": acc_trade_price_24h,
            })

        # 거래대금 기준 내림차순 정렬
        candidates.sort(key=lambda x: x["trade_volume"], reverse=True)

        # 상위 N개 선정
        top_n = CONFIG["top_n"]
        selected = [c["market"] for c in candidates[:top_n]]

        # 호가 스프레드 필터
        result = []
        for market in selected:
            if self._check_spread(market):
                result.append(market)

        return result

    def _check_spread(self, market: str) -> bool:
        """호가 스프레드가 기준 이내인지 확인."""
        orderbook = self.client.get_orderbook(market)
        if not orderbook:
            return False

        units = orderbook.get("orderbook_units", [])
        if not units:
            return False

        best_ask = float(units[0].get("ask_price", 0))
        best_bid = float(units[0].get("bid_price", 0))

        if best_bid <= 0:
            return False

        spread_pct = ((best_ask - best_bid) / best_bid) * 100

        if spread_pct > CONFIG["max_spread_pct"]:
            logger.debug(
                "%s 스프레드 %.2f%% > 기준 %.1f%%, 제외",
                market, spread_pct, CONFIG["max_spread_pct"],
            )
            return False

        return True
