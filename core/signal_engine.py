from dataclasses import dataclass
from config.settings import CONFIG
from utils.logger import logger


@dataclass
class Signal:
    """매매 시그널 결과."""
    action: str       # "BUY", "SELL", "HOLD"
    score: int         # 시그널 강도 (0~100)
    reason: str        # 사유


class SignalEngine:
    """매수/매도 시그널 판단 엔진.

    BB + RSI + MACD + Volume 복합 조건으로 시그널을 생성한다.
    """

    def evaluate_buy(self, indicators: dict) -> Signal:
        """매수 시그널 평가.

        Args:
            indicators: DataCollector.calc_indicators() 결과

        Returns:
            Signal(action, score, reason)
        """
        bb = indicators["bb"]
        rsi = indicators["rsi"]
        macd = indicators["macd"]
        vol = indicators["volume"]

        percent_b = bb["percent_b"].iloc[-1]
        current_rsi = rsi.iloc[-1]
        macd_hist = macd["histogram"].iloc[-1]
        prev_hist = macd["histogram"].iloc[-2]
        volume_ratio = vol["ratio"]

        score = 0
        reasons = []

        # 볼린저밴드 (가중치 40%)
        if percent_b <= -0.1:
            score += 40
            reasons.append(f"BB %b={percent_b:.2f} 강한이탈")
        elif percent_b <= 0.0:
            score += 30
            reasons.append(f"BB %b={percent_b:.2f} 하단터치")

        # RSI (가중치 30%)
        if current_rsi <= 20:
            score += 30
            reasons.append(f"RSI={current_rsi:.1f} 극과매도")
        elif current_rsi <= 30:
            score += 20
            reasons.append(f"RSI={current_rsi:.1f} 과매도")

        # MACD (가중치 20%)
        if macd_hist > prev_hist and macd_hist < 0:
            score += 20
            reasons.append("MACD 반등전환")
        elif macd_hist > prev_hist:
            score += 10
            reasons.append("MACD 히스토그램증가")

        # 거래량 (가중치 10%)
        if volume_ratio >= 2.0:
            score += 10
            reasons.append(f"거래량 {volume_ratio:.1f}x (강)")
        elif volume_ratio >= CONFIG["volume_threshold"]:
            score += 5
            reasons.append(f"거래량 {volume_ratio:.1f}x")

        if score >= 50:
            reason_str = " | ".join(reasons)
            logger.info("매수 시그널 score=%d: %s", score, reason_str)
            return Signal(action="BUY", score=score, reason=reason_str)

        return Signal(action="HOLD", score=score, reason="조건 미충족")

    def evaluate_sell(
        self,
        indicators: dict,
        entry_price: float,
        current_price: float,
        holding_minutes: float,
    ) -> Signal:
        """매도 시그널 평가.

        Args:
            indicators: DataCollector.calc_indicators() 결과
            entry_price: 매수 평균가
            current_price: 현재가
            holding_minutes: 보유 경과 시간 (분)

        Returns:
            Signal(action, score, reason)
        """
        bb = indicators["bb"]
        rsi = indicators["rsi"]

        percent_b = bb["percent_b"].iloc[-1]
        middle_band = bb["middle"].iloc[-1]
        lower_band = bb["lower"].iloc[-1]
        current_rsi = rsi.iloc[-1]

        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # 손절: 고정 손절선
        if pnl_pct <= CONFIG["stop_loss_pct"]:
            return Signal(
                action="SELL", score=100,
                reason=f"손절 {pnl_pct:.2f}% <= {CONFIG['stop_loss_pct']}%",
            )

        # 손절: BB 하단밴드 추가 하락 돌파 (밴드 워킹 다운)
        if current_price < lower_band and percent_b < -0.1:
            return Signal(
                action="SELL", score=90,
                reason=f"밴드워킹다운 %b={percent_b:.2f}",
            )

        # 시간 손절
        if holding_minutes >= CONFIG["time_stop_minutes"]:
            return Signal(
                action="SELL", score=80,
                reason=f"시간손절 {holding_minutes:.0f}분 경과",
            )

        # 익절: 상단밴드 도달
        if CONFIG["take_profit_upper"] and percent_b >= 1.0:
            return Signal(
                action="SELL", score=95,
                reason=f"상단밴드 익절 %b={percent_b:.2f}",
            )

        # 익절: RSI 과매수
        if current_rsi >= 70:
            return Signal(
                action="SELL", score=85,
                reason=f"RSI 과매수 {current_rsi:.1f}",
            )

        # 익절: 중심선 도달
        if CONFIG["take_profit_mid"] and current_price >= middle_band:
            return Signal(
                action="SELL", score=70,
                reason=f"중심선 익절 price={current_price:.0f} >= mid={middle_band:.0f}",
            )

        return Signal(action="HOLD", score=0, reason="보유 유지")
