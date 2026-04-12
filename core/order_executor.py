from utils.upbit_client import UpbitClient
from utils.logger import logger, log_trade
from config.settings import CONFIG


class OrderExecutor:
    """주문 실행 모듈.

    시장가 매수/매도를 실행하고 거래 로그를 기록한다.
    """

    def __init__(self, client: UpbitClient):
        self.client = client

    def buy(
        self, market: str, amount: float, score: int = 0, reason: str = ""
    ) -> dict | None:
        """시장가 매수.

        Args:
            market: 마켓 코드 (예: KRW-BTC)
            amount: 매수 금액 (KRW)
            score: 시그널 점수
            reason: 매수 사유

        Returns:
            주문 결과 또는 None
        """
        # 호가 스프레드 확인
        if not self._check_spread(market):
            logger.warning("%s 스프레드 과다 - 매수 보류", market)
            return None

        logger.info("매수 주문: %s %.0f원", market, amount)
        result = self.client.buy_market_order(market, amount)

        if result and "error" not in result:
            price = float(result.get("price", 0)) or amount
            log_trade(
                action="BUY",
                market=market,
                price=price,
                amount=amount,
                score=score,
                reason=reason,
            )
            logger.info("매수 체결: %s %s", market, result)
            return result

        logger.error("매수 실패: %s %s", market, result)
        return None

    def sell(
        self,
        market: str,
        volume: float,
        entry_price: float = 0.0,
        current_price: float = 0.0,
        reason: str = "",
    ) -> dict | None:
        """시장가 매도.

        Args:
            market: 마켓 코드 (예: KRW-BTC)
            volume: 매도 수량
            entry_price: 매수 평균가 (PnL 계산용)
            current_price: 현재가 (PnL 계산용)
            reason: 매도 사유

        Returns:
            주문 결과 또는 None
        """
        logger.info("매도 주문: %s 수량=%.8f", market, volume)
        result = self.client.sell_market_order(market, volume)

        if result and "error" not in result:
            pnl = 0.0
            pnl_pct = 0.0
            if entry_price > 0 and current_price > 0:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                pnl = (current_price - entry_price) * volume

            log_trade(
                action="SELL",
                market=market,
                price=current_price,
                amount=volume,
                reason=reason,
                pnl=pnl,
                pnl_pct=pnl_pct,
            )
            logger.info(
                "매도 체결: %s PnL=%.0f원(%.2f%%)", market, pnl, pnl_pct
            )
            return result

        logger.error("매도 실패: %s %s", market, result)
        return None

    def _check_spread(self, market: str) -> bool:
        """매매 전 호가 스프레드 재확인 (0.3% 이상이면 보류)."""
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
        return spread_pct < 0.3
