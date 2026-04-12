"""자동매매 엔진 (AutoTrader).

별도 데몬 스레드에서 1초 간격으로 매매 루프를 실행한다.
매수 종목 선정 → 매도 조건 평가 → 신규 매수 실행.
"""

import logging
import threading
import time
from datetime import timedelta

import pandas as pd
from django.utils import timezone

from . import upbit_client
from .models import TradeRecord, FailedMarket, AskRecord
from .market_analyzer import get_market_state
from .coin_selector import select_coin
from .indicators import (
    calculate_rsi, calculate_macd, calculate_bollinger_bands, calculate_stochastic,
)
from .telegram_bot import send_message as tg_notify

logger = logging.getLogger(__name__)

# 수수료율
FEE_RATE = 0.0005
MAX_ACTIVE_TRADES = 3
MIN_KRW_BALANCE = 10_000


class AutoTrader:
    """자동매매 엔진."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._budget: float = 0
        self._active_trades: dict[str, dict] = {}  # market -> trade info
        self._trade_logs: list[str] = []
        self._retry_count = 0
        self._max_retries = 3

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def trade_logs(self) -> list[str]:
        return self._trade_logs[-50:]

    def start(self, budget: float):
        """자동매매 시작."""
        if self._running:
            return
        self._budget = budget
        self._running = True
        self._retry_count = 0

        # DB에서 활성 거래 복원
        self._restore_trades()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log(f"자동매매 시작 (예산: {budget:,.0f}원)")
        tg_notify(f"🟢 자동매매 시작\n예산: {budget:,.0f}원")

    def stop(self):
        """자동매매 중지."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._log("자동매매 중지")
        tg_notify("🔴 자동매매 중지")

    def _log(self, msg: str):
        """거래 로그 기록."""
        ts = timezone.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self._trade_logs.append(entry)
        logger.info(msg)

    def _restore_trades(self):
        """DB에서 활성 거래 복원."""
        active = TradeRecord.objects.filter(is_active=True)
        for rec in active:
            self._active_trades[rec.market] = {
                "buy_price": rec.buy_price,
                "highest_price": rec.highest_price,
                "uuid": rec.uuid,
                "created_at": rec.created_at,
                "buy_krw_price": rec.buy_krw_price,
            }
        if self._active_trades:
            self._log(f"기존 거래 복원: {list(self._active_trades.keys())}")

    def _run_loop(self):
        """메인 매매 루프 (1초 간격)."""
        while self._running:
            try:
                self._tick()
                self._retry_count = 0
            except Exception as e:
                self._retry_count += 1
                self._log(f"에러 발생 ({self._retry_count}/{self._max_retries}): {e}")
                logger.error("매매 루프 에러", exc_info=True)
                if self._retry_count >= self._max_retries:
                    self._log("최대 재시도 횟수 초과 - 자동매매 중단")
                    tg_notify(f"⚠️ 자동매매 중단\n에러 {self._max_retries}회 연속 발생: {e}")
                    self._running = False
                    return
            time.sleep(1)

    def _tick(self):
        """매매 루프 1회 실행."""
        # 1) 계좌 + 시장 상태 조회
        accounts = upbit_client.get_accounts()
        market_state = get_market_state()

        # 보유 코인 목록 (accounts 기반)
        holding_currencies = set()
        balances = {}
        for a in accounts:
            cur = a.get("currency", "")
            bal = float(a.get("balance", 0))
            if cur != "KRW" and bal > 0:
                market = f"KRW-{cur}"
                holding_currencies.add(market)
                balances[market] = bal

        # 2) 사용자 수동 매도 감지
        self._detect_manual_sell(holding_currencies)

        # 3) 보유 종목 매도 조건 평가
        for market in list(self._active_trades.keys()):
            self._evaluate_sell(market, market_state, balances)

        # 4) 신규 매수
        self._evaluate_buy(accounts, market_state)

    def _detect_manual_sell(self, holding: set[str]):
        """사용자가 수동으로 매도한 경우 감지."""
        for market in list(self._active_trades.keys()):
            if market not in holding:
                self._log(f"수동 매도 감지: {market}")
                TradeRecord.objects.filter(
                    market=market, is_active=True
                ).update(is_active=False)
                del self._active_trades[market]

    # ── 매도 로직 ──────────────────────────────────────

    def _evaluate_sell(
        self, market: str, market_state: str, balances: dict
    ):
        """매도 조건 평가 및 실행."""
        trade = self._active_trades.get(market)
        if not trade:
            return

        # 현재가 조회
        ticker = upbit_client.get_ticker([market])
        if not ticker:
            return
        current_price = float(ticker[0].get("trade_price", 0))
        change_rate = abs(float(ticker[0].get("signed_change_rate", 0)) * 100)

        if current_price <= 0:
            return

        buy_price = trade["buy_price"]
        highest = trade["highest_price"]

        # 최고가 갱신
        if current_price > highest:
            trade["highest_price"] = current_price
            TradeRecord.objects.filter(
                market=market, is_active=True
            ).update(highest_price=current_price)

        pnl_pct = ((current_price - buy_price) / buy_price) * 100
        real_pnl = self._calc_real_pnl(buy_price, current_price)

        # 보유 시간 계산
        created = trade["created_at"]
        elapsed = (timezone.now() - created).total_seconds()

        # 기술적 지표 조회
        indicators = self._get_indicators(market)

        sell_reason = self._check_sell_conditions(
            current_price, buy_price, highest, pnl_pct,
            market_state, elapsed, change_rate, indicators,
        )

        if not sell_reason:
            return

        # 매도 실행
        volume = balances.get(market, 0)
        if volume <= 0:
            return

        self._log(
            f"매도 시도: {market} | 사유={sell_reason} | "
            f"매수가={buy_price:,.2f} 현재가={current_price:,.2f} "
            f"수익률={real_pnl:.2f}%"
        )

        result = upbit_client.sell_market_order(market, volume)
        if result and result.get("uuid"):
            # 매도 기록
            TradeRecord.objects.filter(
                market=market, is_active=True
            ).update(is_active=False)
            AskRecord.objects.update_or_create(
                market=market,
                defaults={"recorded_at": timezone.now()},
            )
            del self._active_trades[market]
            self._log(
                f"매도 체결: {market} | 수익률={real_pnl:.2f}% | {sell_reason}"
            )
            emoji = "💰" if real_pnl >= 0 else "📉"
            tg_notify(
                f"{emoji} 매도 체결: {market}\n"
                f"매수가: {buy_price:,.2f}원\n"
                f"매도가: {current_price:,.2f}원\n"
                f"수익률: {real_pnl:+.2f}%\n"
                f"사유: {sell_reason}"
            )
        else:
            self._log(f"매도 실패: {market}")

    def _get_indicators(self, market: str) -> dict | None:
        """기술적 지표 계산. 캔들 데이터 조회 후 RSI/MACD/BB/스토캐스틱 반환."""
        candles = upbit_client.get_candles_minutes(market, unit=3, count=50)
        if not candles or len(candles) < 26:
            return None

        df = pd.DataFrame(candles[::-1])
        df = df.rename(columns={
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        })

        try:
            return {
                "rsi": calculate_rsi(df),
                "macd": calculate_macd(df),
                "bb": calculate_bollinger_bands(df),
                "stoch": calculate_stochastic(df),
            }
        except Exception as e:
            logger.warning("%s 지표 계산 실패: %s", market, e)
            return None

    def _check_sell_conditions(
        self,
        current: float,
        buy: float,
        highest: float,
        pnl_pct: float,
        market_state: str,
        elapsed: float,
        change_rate: float,
        indicators: dict | None = None,
    ) -> str | None:
        """매도 조건 확인. 반환: 매도 사유 문자열 또는 None."""
        # 손절: 고변동성 -4%, 일반 -2%
        if change_rate >= 5:
            if current <= buy * 0.96:
                return f"고변동성 손절 ({pnl_pct:.1f}%)"
        else:
            if current <= buy * 0.98:
                return f"일반 손절 ({pnl_pct:.1f}%)"

        # 트레일링 스탑: 2% 이상 수익 후 최고가 대비 1% 하락
        if current >= buy * 1.02 and highest > 0:
            if current <= highest * 0.99:
                return f"트레일링스탑 (최고가={highest:,.2f} 현재={current:,.2f})"

        # 수익 실현: 1% 이상 + 보합/하락장
        if current >= buy * 1.01 and market_state in ("neutral", "bearish"):
            return f"수익실현 1% ({market_state})"

        # ── 기술적 지표 기반 매도 (수익 0.8% 이상일 때만) ──
        if indicators and pnl_pct > 0.8:
            rsi = indicators["rsi"]
            macd_hist = indicators["macd"]["histogram"]
            bb_upper = indicators["bb"]["upper"]
            stoch_k = indicators["stoch"]["k"]

            # RSI 극과매수 + 볼린저 상단 돌파 → 고점 매도
            if rsi > 78 and current > bb_upper:
                return f"지표매도: RSI 과매수({rsi:.0f}) + BB상단 돌파"

            # RSI 과매수 + MACD 하락 + 스토캐스틱 고점 → 복합 하락 신호
            if rsi > 75 and macd_hist < 0 and stoch_k > 80:
                return f"지표매도: RSI({rsi:.0f}) + MACD↓ + 스토캐스틱({stoch_k:.0f})"

        # 시간 기반 매도
        if market_state == "bullish" and elapsed >= 360:
            if current >= buy * 1.01:
                return f"시간매도 5분 (상승장, {pnl_pct:.1f}%)"
        elif elapsed >= 600:
            if current >= buy * 1.01:
                return f"시간매도 10분 ({market_state}, {pnl_pct:.1f}%)"

        return None

    def _calc_real_pnl(self, buy_price: float, sell_price: float) -> float:
        """수수료 반영 실질 수익률."""
        real_buy = buy_price * (1 + FEE_RATE)
        real_sell = sell_price * (1 - FEE_RATE)
        return ((real_sell - real_buy) / real_buy) * 100

    # ── 매수 로직 ──────────────────────────────────────

    def _evaluate_buy(self, accounts: list[dict], market_state: str):
        """매수 조건 평가 및 실행."""
        # 동시 보유 제한
        if len(self._active_trades) >= MAX_ACTIVE_TRADES:
            return

        # KRW 잔고 확인
        krw = 0.0
        for a in accounts:
            if a.get("currency") == "KRW":
                krw = float(a.get("balance", 0))
                break

        buy_amount = min(self._budget, krw)
        # 수수료(0.05%) 반영 후 1원 단위 내림
        buy_amount = int(buy_amount / (1 + FEE_RATE))
        if buy_amount < MIN_KRW_BALANCE:
            return

        # 전체 시세 조회 + 종목 선정
        markets = upbit_client.get_krw_markets()
        tickers = upbit_client.get_ticker(markets)
        if not tickers:
            return

        # 거래대금 순 정렬
        tickers.sort(
            key=lambda t: float(t.get("acc_trade_price_24h", 0)), reverse=True
        )

        active_set = set(self._active_trades.keys())
        selected = select_coin(tickers, active_set)
        if not selected:
            return

        # 잔고 초과 방지 (수수료 포함 금액이 잔고를 넘지 않도록)
        buy_amount = min(buy_amount, int(krw / (1 + FEE_RATE)))

        self._log(f"매수 시도: {selected} | 금액={buy_amount:,.0f}원")

        result = upbit_client.buy_market_order(selected, buy_amount)
        if result and result.get("uuid"):
            order_uuid = result["uuid"]
            # 현재가 조회
            t = upbit_client.get_ticker([selected])
            price = float(t[0]["trade_price"]) if t else buy_amount

            # DB + 메모리 저장
            rec, _ = TradeRecord.objects.update_or_create(
                market=selected,
                defaults={
                    "buy_price": price,
                    "highest_price": price,
                    "uuid": order_uuid,
                    "is_active": True,
                    "buy_krw_price": buy_amount,
                },
            )
            self._active_trades[selected] = {
                "buy_price": price,
                "highest_price": price,
                "uuid": order_uuid,
                "created_at": rec.created_at,
                "buy_krw_price": buy_amount,
            }
            self._log(f"매수 체결: {selected} @ {price:,.2f}원")
            tg_notify(
                f"🔵 매수 체결: {selected}\n"
                f"매수가: {price:,.2f}원\n"
                f"투입금: {buy_amount:,.0f}원"
            )
        else:
            # 실패 기록
            FailedMarket.objects.get_or_create(market=selected)
            self._log(f"매수 실패: {selected} (FailedMarket 등록)")


# 싱글턴 인스턴스
_trader: AutoTrader | None = None


def get_trader() -> AutoTrader:
    global _trader
    if _trader is None:
        _trader = AutoTrader()
    return _trader
