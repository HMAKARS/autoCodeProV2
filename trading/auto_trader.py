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
    calculate_atr, calculate_vwap,
)
from .telegram_bot import send_message as tg_notify

logger = logging.getLogger(__name__)

# 수수료율 (편도). 왕복은 FEE_RATE * 2
FEE_RATE = 0.0005
MAX_ACTIVE_TRADES = 3
MIN_KRW_BALANCE = 10_000
MIN_ORDER_KRW = 5_500  # 업비트 최소 주문 (5,000원) + 여유

# ATR 기반 손절 파라미터 (단타 표준)
ATR_MULTIPLIER = 1.5        # 단타에는 1.5x가 표준
MIN_STOP_LOSS_PCT = 1.0     # 손절 최소 폭
MAX_STOP_LOSS_PCT = 3.0     # 손절 최대 폭 (단타는 타이트하게)
DEFAULT_STOP_LOSS_PCT = 1.5 # ATR 계산 실패 시 기본값

# Risk/Reward 비율 (단타 표준)
RR_FIRST_TARGET = 1.5       # 1차 익절: R:R 1:1.5 (50% 매도)
RR_SECOND_TARGET = 3.0      # 2차 익절: R:R 1:3 (나머지 50%)
FIRST_SELL_RATIO = 0.5      # 1차 매도 비율


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
            # 기존 DB에 손절가 없으면(구 레코드) 매수가 기준 -1.5%로 설정
            stop_loss = rec.stop_loss_price
            if stop_loss <= 0 and rec.buy_price > 0:
                stop_loss = rec.buy_price * (1 - DEFAULT_STOP_LOSS_PCT / 100)

            self._active_trades[rec.market] = {
                "buy_price": rec.buy_price,
                "highest_price": rec.highest_price,
                "stop_loss_price": stop_loss,
                "first_sell_done": rec.first_sell_done,
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
        """매도 조건 평가 및 실행 (부분매도 지원)."""
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
        first_sell_done = trade.get("first_sell_done", False)
        stop_loss_price = trade.get("stop_loss_price", 0)

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

        # 1차/2차 익절가 계산 (R:R 기반)
        first_target, second_target = self._calc_targets(buy_price, stop_loss_price)

        sell_action = self._check_sell_conditions(
            current_price, buy_price, highest, pnl_pct,
            market_state, elapsed, change_rate, indicators,
            stop_loss_price, first_sell_done,
            first_target, second_target,
        )

        if not sell_action:
            return

        reason, sell_ratio = sell_action

        # 매도 실행
        total_volume = balances.get(market, 0)
        if total_volume <= 0:
            return

        sell_volume = total_volume * sell_ratio

        # 부분매도 금액이 최소주문 미만이면 전량 매도로 전환
        if sell_ratio < 1.0:
            estimated_value = sell_volume * current_price
            if estimated_value < MIN_ORDER_KRW:
                sell_volume = total_volume
                sell_ratio = 1.0
                reason = f"{reason} (잔액소액→전량)"

        self._log(
            f"매도 시도: {market} | 사유={reason} | 비율={sell_ratio*100:.0f}% | "
            f"매수가={buy_price:,g} 현재가={current_price:,g} 수익률={real_pnl:.2f}%"
        )

        result = upbit_client.sell_market_order(market, sell_volume)
        if not result or not result.get("uuid"):
            self._log(f"매도 실패: {market}")
            return

        if sell_ratio < 1.0:
            # 1차 부분 매도 → 포지션 유지, first_sell_done 표시
            trade["first_sell_done"] = True
            # 손절가를 break-even(매수가+수수료)로 상향 (본전 방어)
            break_even = buy_price * (1 + FEE_RATE * 2)
            trade["stop_loss_price"] = break_even
            TradeRecord.objects.filter(
                market=market, is_active=True
            ).update(
                first_sell_done=True,
                stop_loss_price=break_even,
            )
            self._log(
                f"1차 익절: {market} 50% 매도 | 수익률={real_pnl:.2f}% | "
                f"손절선 → 본전({break_even:,g}) 상향"
            )
            tg_notify(
                f"💵 1차 익절 (50%): {market}\n"
                f"매수가: {buy_price:,g}원\n"
                f"매도가: {current_price:,g}원\n"
                f"수익률: {real_pnl:+.2f}%\n"
                f"손절선 → 본전 상향\n"
                f"사유: {reason}"
            )
        else:
            # 전량 매도 → 포지션 청산
            TradeRecord.objects.filter(
                market=market, is_active=True
            ).update(is_active=False)
            AskRecord.objects.update_or_create(
                market=market,
                defaults={"recorded_at": timezone.now()},
            )
            del self._active_trades[market]
            self._log(
                f"매도 체결: {market} | 수익률={real_pnl:.2f}% | {reason}"
            )
            emoji = "💰" if real_pnl >= 0 else "📉"
            tg_notify(
                f"{emoji} 매도 체결: {market}\n"
                f"매수가: {buy_price:,g}원\n"
                f"매도가: {current_price:,g}원\n"
                f"수익률: {real_pnl:+.2f}%\n"
                f"사유: {reason}"
            )

    def _calc_targets(
        self, buy_price: float, stop_loss_price: float
    ) -> tuple[float, float]:
        """1차/2차 익절가 계산.

        R:R 비율 기반 + 왕복 수수료(0.1%) 반영.
        """
        if stop_loss_price <= 0 or buy_price <= 0:
            # 기본값: 손절 -1.5% 가정
            stop_distance = buy_price * 0.015
        else:
            stop_distance = buy_price - stop_loss_price

        fee_buffer = buy_price * FEE_RATE * 2  # 왕복 수수료 보정
        first_target = buy_price + stop_distance * RR_FIRST_TARGET + fee_buffer
        second_target = buy_price + stop_distance * RR_SECOND_TARGET + fee_buffer
        return first_target, second_target

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
                "vwap": calculate_vwap(df),
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
        indicators: dict | None,
        stop_loss_price: float,
        first_sell_done: bool,
        first_target: float,
        second_target: float,
    ) -> tuple[str, float] | None:
        """매도 조건 확인.

        Returns:
            (매도 사유, 매도 비율) - 매도 비율은 0.5(1차) 또는 1.0(전량).
            None이면 보유 유지.
        """
        # ── 1) 손절 (최우선) ─────────────────────────────────
        # 1차 익절 전: 원래 ATR 손절가
        # 1차 익절 후: break-even(본전)으로 상향된 손절가 (stop_loss_price가 이미 업데이트되어 있음)
        if stop_loss_price > 0 and current <= stop_loss_price:
            label = "본전손절" if first_sell_done else "손절"
            return (
                f"{label} ({pnl_pct:.2f}% / 손절선={stop_loss_price:,g})",
                1.0,
            )

        # ── 2) 1차 익절 미완료 상태 ─────────────────────────
        if not first_sell_done:
            # 1차 목표가 도달 → 50% 매도
            if current >= first_target:
                return (
                    f"1차 익절 R:R 1:{RR_FIRST_TARGET} ({pnl_pct:.2f}% / 목표={first_target:,g})",
                    FIRST_SELL_RATIO,
                )
            return None

        # ── 3) 1차 익절 완료 상태 - 남은 50% 관리 ───────────
        # 3-1) 2차 목표가 도달 → 전량 매도
        if current >= second_target:
            return (
                f"2차 익절 R:R 1:{RR_SECOND_TARGET} ({pnl_pct:.2f}% / 목표={second_target:,g})",
                1.0,
            )

        # 3-2) 트레일링 스탑: 최고가 대비 1% 하락 → 전량 매도
        if highest > 0 and current <= highest * 0.99:
            return (
                f"트레일링스탑 (최고가={highest:,g} 현재={current:,g} / {pnl_pct:.2f}%)",
                1.0,
            )

        # 3-3) VWAP 이탈: 추세 종료 신호 → 전량 매도
        if indicators and indicators.get("vwap"):
            vwap = indicators["vwap"]
            if current < vwap:
                return (
                    f"VWAP 이탈 (VWAP={vwap:,g} 현재={current:,g} / {pnl_pct:.2f}%)",
                    1.0,
                )

        # 3-4) 기술적 지표 기반 조기 매도 (고점 징후)
        if indicators:
            rsi = indicators.get("rsi", 0)
            macd_hist = indicators.get("macd", {}).get("histogram", 0)
            bb_upper = indicators.get("bb", {}).get("upper", 0)
            stoch_k = indicators.get("stoch", {}).get("k", 0)

            # RSI 극과매수 + BB 상단 돌파
            if rsi > 78 and bb_upper > 0 and current > bb_upper:
                return (
                    f"지표매도: RSI({rsi:.0f}) + BB상단 돌파",
                    1.0,
                )

            # RSI 과매수 + MACD 하락 + 스토캐스틱 고점 복합
            if rsi > 75 and macd_hist < 0 and stoch_k > 80:
                return (
                    f"지표매도: RSI({rsi:.0f}) + MACD↓ + Stoch({stoch_k:.0f})",
                    1.0,
                )

        # 3-5) 시간 기반 매도 (1차 익절 후에도 오래 정체되면 청산)
        if market_state == "bullish" and elapsed >= 360:
            return (
                f"시간매도 5분 (상승장, {pnl_pct:.2f}%)",
                1.0,
            )
        if market_state != "bullish" and elapsed >= 600:
            return (
                f"시간매도 10분 ({market_state}, {pnl_pct:.2f}%)",
                1.0,
            )

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

            # ATR 기반 손절가 계산 (매수 시점 고정)
            stop_loss_price, stop_pct = self._calc_stop_loss_price(selected, price)

            # DB + 메모리 저장
            rec, _ = TradeRecord.objects.update_or_create(
                market=selected,
                defaults={
                    "buy_price": price,
                    "highest_price": price,
                    "stop_loss_price": stop_loss_price,
                    "first_sell_done": False,
                    "uuid": order_uuid,
                    "is_active": True,
                    "buy_krw_price": buy_amount,
                },
            )
            self._active_trades[selected] = {
                "buy_price": price,
                "highest_price": price,
                "stop_loss_price": stop_loss_price,
                "first_sell_done": False,
                "uuid": order_uuid,
                "created_at": rec.created_at,
                "buy_krw_price": buy_amount,
            }
            # 1차/2차 목표가 미리 계산해서 로그
            first_target, second_target = self._calc_targets(price, stop_loss_price)
            first_pct = ((first_target - price) / price) * 100
            second_pct = ((second_target - price) / price) * 100
            self._log(
                f"매수 체결: {selected} @ {price:,g}원 | "
                f"손절={stop_loss_price:,g}(-{stop_pct:.2f}%) / "
                f"1차={first_target:,g}(+{first_pct:.2f}%) / "
                f"2차={second_target:,g}(+{second_pct:.2f}%)"
            )
            tg_notify(
                f"🔵 매수 체결: {selected}\n"
                f"매수가: {price:,g}원\n"
                f"손절선: {stop_loss_price:,g}원 (-{stop_pct:.2f}%)\n"
                f"1차 익절(50%): {first_target:,g}원 (+{first_pct:.2f}%)\n"
                f"2차 익절(전량): {second_target:,g}원 (+{second_pct:.2f}%)\n"
                f"투입금: {buy_amount:,.0f}원"
            )
        else:
            # 실패 기록
            FailedMarket.objects.get_or_create(market=selected)
            self._log(f"매수 실패: {selected} (FailedMarket 등록)")

    def _calc_stop_loss_price(self, market: str, buy_price: float) -> tuple[float, float]:
        """ATR 기반 손절가 계산.

        Returns:
            (손절가, 손절폭 %)
        """
        candles = upbit_client.get_candles_minutes(market, unit=3, count=30)
        if not candles or len(candles) < 15:
            # 데이터 부족 시 기본값
            stop_price = buy_price * (1 - DEFAULT_STOP_LOSS_PCT / 100)
            return stop_price, DEFAULT_STOP_LOSS_PCT

        df = pd.DataFrame(candles[::-1])
        df = df.rename(columns={
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        })

        try:
            atr = calculate_atr(df, period=14)
            if atr <= 0 or pd.isna(atr):
                raise ValueError("ATR 계산 오류")

            # ATR × MULTIPLIER 를 손절 거리로 사용
            stop_distance = atr * ATR_MULTIPLIER
            stop_pct = (stop_distance / buy_price) * 100

            # 최소/최대 제한
            stop_pct = max(MIN_STOP_LOSS_PCT, min(MAX_STOP_LOSS_PCT, stop_pct))
            stop_price = buy_price * (1 - stop_pct / 100)

            logger.info(
                "%s ATR 손절가 계산: ATR=%.4f → 손절폭=%.2f%% → 손절선=%.4f",
                market, atr, stop_pct, stop_price,
            )
            return stop_price, stop_pct
        except Exception as e:
            logger.warning("%s ATR 계산 실패: %s, 기본값 사용", market, e)
            stop_price = buy_price * (1 - DEFAULT_STOP_LOSS_PCT / 100)
            return stop_price, DEFAULT_STOP_LOSS_PCT


# 싱글턴 인스턴스
_trader: AutoTrader | None = None


def get_trader() -> AutoTrader:
    global _trader
    if _trader is None:
        _trader = AutoTrader()
    return _trader
