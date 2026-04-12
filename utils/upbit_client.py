import time
import pyupbit
from config.settings import CONFIG


class UpbitClient:
    """업비트 API 래퍼.

    pyupbit를 감싸서 rate limit 관리 및 에러 핸들링을 제공한다.
    """

    def __init__(self):
        access = CONFIG["access_key"]
        secret = CONFIG["secret_key"]
        if access and secret:
            self.upbit = pyupbit.Upbit(access, secret)
        else:
            self.upbit = None
        self._last_request_time = 0.0
        self._min_interval = 0.1  # 초당 10회 제한

    def _throttle(self):
        """API rate limit 준수를 위한 요청 간격 조절."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def get_krw_markets(self) -> list[str]:
        """KRW 마켓 전체 목록 조회."""
        self._throttle()
        tickers = pyupbit.get_tickers(fiat="KRW")
        return tickers or []

    def get_ticker_info(self, markets: list[str]) -> list[dict]:
        """티커 정보 조회 (현재가, 거래대금, 변동률 등)."""
        self._throttle()
        result = []
        for market in markets:
            self._throttle()
            info = pyupbit.get_current_price(market)
            result.append({"market": market, "trade_price": info})
        return result

    def get_tickers_detail(self, markets: list[str]) -> list[dict] | None:
        """여러 마켓의 상세 티커 정보를 한 번에 조회."""
        self._throttle()
        url = "https://api.upbit.com/v1/ticker"
        params = {"markets": ",".join(markets)}
        try:
            import requests
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def get_orderbook(self, market: str) -> dict | None:
        """호가 정보 조회."""
        self._throttle()
        orderbook = pyupbit.get_orderbook(market)
        if orderbook and len(orderbook) > 0:
            return orderbook[0] if isinstance(orderbook, list) else orderbook
        return None

    def get_ohlcv(
        self, market: str, interval: str = "minute5", count: int = 100
    ):
        """캔들(OHLCV) 데이터 조회.

        Args:
            market: 마켓 코드 (예: KRW-BTC)
            interval: 캔들 단위 (minute1, minute5, minute15 등)
            count: 조회할 캔들 수

        Returns:
            pandas DataFrame (open, high, low, close, volume)
        """
        self._throttle()
        df = pyupbit.get_ohlcv(market, interval=interval, count=count)
        return df

    def get_balance(self, ticker: str = "KRW") -> float:
        """잔고 조회.

        Args:
            ticker: 조회할 화폐/코인 (기본값: KRW)

        Returns:
            잔고 금액
        """
        if not self.upbit:
            return 0.0
        self._throttle()
        balance = self.upbit.get_balance(ticker)
        return balance or 0.0

    def get_avg_buy_price(self, ticker: str) -> float:
        """평균 매수가 조회."""
        if not self.upbit:
            return 0.0
        self._throttle()
        price = self.upbit.get_avg_buy_price(ticker)
        return price or 0.0

    def buy_market_order(self, market: str, amount: float) -> dict | None:
        """시장가 매수.

        Args:
            market: 마켓 코드 (예: KRW-BTC)
            amount: 매수 금액 (KRW)

        Returns:
            주문 결과 dict 또는 None
        """
        if not self.upbit:
            return None
        self._throttle()
        result = self.upbit.buy_market_order(market, amount)
        return result

    def sell_market_order(self, market: str, volume: float) -> dict | None:
        """시장가 매도.

        Args:
            market: 마켓 코드 (예: KRW-BTC)
            volume: 매도 수량

        Returns:
            주문 결과 dict 또는 None
        """
        if not self.upbit:
            return None
        self._throttle()
        result = self.upbit.sell_market_order(market, volume)
        return result

    def get_holding_coins(self) -> list[dict]:
        """보유 중인 코인 목록 조회.

        Returns:
            [{"currency": "BTC", "balance": 0.001, "avg_buy_price": 50000000}, ...]
        """
        if not self.upbit:
            return []
        self._throttle()
        balances = self.upbit.get_balances()
        holdings = []
        for b in balances:
            if b["currency"] == "KRW":
                continue
            balance = float(b.get("balance", 0))
            if balance > 0:
                holdings.append({
                    "currency": b["currency"],
                    "balance": balance,
                    "avg_buy_price": float(b.get("avg_buy_price", 0)),
                })
        return holdings
