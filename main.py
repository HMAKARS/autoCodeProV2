"""업비트 볼린저밴드 단타 자동매매 봇.

전략서(upbit_scalping_strategy.md) 기반 구현.
5초 간격 메인 루프로 BB + RSI + MACD + Volume 복합 시그널을 판단하여
자동 매수/매도를 실행한다.
"""

import time
import signal
import sys

from config.settings import CONFIG
from utils.upbit_client import UpbitClient
from utils.logger import logger
from core.market_selector import MarketSelector
from core.data_collector import DataCollector
from core.signal_engine import SignalEngine
from core.order_executor import OrderExecutor
from core.risk_manager import RiskManager


class ScalpingBot:
    """메인 스캘핑 봇."""

    def __init__(self):
        self.client = UpbitClient()
        self.market_selector = MarketSelector(self.client)
        self.data_collector = DataCollector(self.client)
        self.signal_engine = SignalEngine()
        self.order_executor = OrderExecutor(self.client)
        self.risk_manager = RiskManager(self.client)
        self._running = True

    def start(self):
        """봇 시작."""
        logger.info("=" * 50)
        logger.info("스캘핑 봇 시작")
        logger.info("매매금: %s원 | 최대 보유: %d개 | 손절: %.1f%%",
                     f"{CONFIG['buy_amount']:,}",
                     CONFIG["max_positions"],
                     CONFIG["stop_loss_pct"])
        logger.info("=" * 50)

        # API 키 확인
        if not CONFIG["access_key"] or not CONFIG["secret_key"]:
            logger.error("업비트 API 키가 설정되지 않았습니다. .env 파일을 확인하세요.")
            sys.exit(1)

        # 기존 보유 포지션 동기화
        self.risk_manager.sync_positions()
        if self.risk_manager.positions:
            logger.info("기존 보유 포지션: %s",
                         list(self.risk_manager.positions.keys()))

        # 종료 시그널 핸들러
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        self._main_loop()

    def _main_loop(self):
        """5초 간격 메인 루프."""
        while self._running:
            try:
                self._tick()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("메인 루프 에러: %s", e, exc_info=True)

            time.sleep(CONFIG["loop_interval"])

        logger.info("봇 종료")

    def _tick(self):
        """메인 루프 1회 실행."""
        # 1) 거래 대상 코인 선정 (30분 캐시)
        targets = self.market_selector.get_top_volume_coins()
        if not targets:
            logger.debug("거래 대상 코인 없음")
            return

        # 보유 중인 코인도 포함
        holding_markets = list(self.risk_manager.positions.keys())
        all_markets = list(dict.fromkeys(targets + holding_markets))

        for market in all_markets:
            try:
                self._process_coin(market)
            except Exception as e:
                logger.error("%s 처리 중 에러: %s", market, e)

    def _process_coin(self, market: str):
        """개별 코인 매매 판단 및 실행."""
        # 캔들 데이터 조회
        df = self.data_collector.get_candles(market)
        if df is None:
            return

        # 지표 계산
        indicators = self.data_collector.calc_indicators(df)
        current_price = df["close"].iloc[-1]

        # 보유 여부에 따라 매도/매수 판단
        position = self.risk_manager.get_position(market)

        if position:
            self._evaluate_sell(market, indicators, position, current_price)
        else:
            self._evaluate_buy(market, indicators, current_price)

    def _evaluate_buy(self, market: str, indicators: dict, current_price: float):
        """매수 판단 및 실행."""
        if not self.risk_manager.can_buy(market):
            return

        signal_result = self.signal_engine.evaluate_buy(indicators)
        if signal_result.action != "BUY":
            return

        # 포지션 사이즈 계산
        amount = self.risk_manager.calc_position_size(signal_result.score)
        if amount <= 0:
            return

        # 매수 실행
        result = self.order_executor.buy(
            market=market,
            amount=amount,
            score=signal_result.score,
            reason=signal_result.reason,
        )

        if result:
            # 체결 후 포지션 등록
            ticker = market.replace("KRW-", "")
            bought_volume = self.client.get_balance(ticker)
            avg_price = self.client.get_avg_buy_price(ticker)
            if bought_volume > 0:
                self.risk_manager.add_position(
                    market=market,
                    entry_price=avg_price,
                    volume=bought_volume,
                )

    def _evaluate_sell(
        self, market: str, indicators: dict, position, current_price: float
    ):
        """매도 판단 및 실행."""
        holding_minutes = self.risk_manager.get_holding_minutes(market)

        signal_result = self.signal_engine.evaluate_sell(
            indicators=indicators,
            entry_price=position.entry_price,
            current_price=current_price,
            holding_minutes=holding_minutes,
        )

        if signal_result.action != "SELL":
            return

        # 매도 실행
        pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
        pnl = (current_price - position.entry_price) * position.volume

        result = self.order_executor.sell(
            market=market,
            volume=position.volume,
            entry_price=position.entry_price,
            current_price=current_price,
            reason=signal_result.reason,
        )

        if result:
            self.risk_manager.remove_position(market, pnl=pnl)

    def _shutdown(self, signum, frame):
        """안전한 종료."""
        logger.info("종료 시그널 수신 (%s)", signum)
        self._running = False


def main():
    bot = ScalpingBot()
    bot.start()


if __name__ == "__main__":
    main()
