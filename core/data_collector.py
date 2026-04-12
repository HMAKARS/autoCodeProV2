import pandas as pd
from utils.upbit_client import UpbitClient
from utils.logger import logger
from config.settings import CONFIG
from indicators.bollinger import calc_bollinger
from indicators.rsi import calc_rsi
from indicators.macd import calc_macd
from indicators.volume import calc_volume_ratio


class DataCollector:
    """캔들 데이터 수집 및 지표 계산 모듈."""

    def __init__(self, client: UpbitClient):
        self.client = client

    def get_candles(self, market: str) -> pd.DataFrame | None:
        """캔들 데이터 조회.

        Args:
            market: 마켓 코드 (예: KRW-BTC)

        Returns:
            OHLCV DataFrame 또는 None
        """
        interval = f"minute{CONFIG['candle_interval']}"
        count = CONFIG["candle_count"]

        df = self.client.get_ohlcv(market, interval=interval, count=count)
        if df is None or df.empty:
            logger.warning("%s 캔들 데이터 조회 실패", market)
            return None

        return df

    def calc_indicators(self, df: pd.DataFrame) -> dict:
        """모든 기술적 지표를 한 번에 계산.

        Returns:
            {
                "bb": {upper, middle, lower, percent_b, bandwidth},
                "rsi": RSI Series,
                "macd": {macd, signal, histogram},
                "volume": {current_volume, avg_volume, ratio},
            }
        """
        bb = calc_bollinger(
            df, period=CONFIG["bb_period"], std=CONFIG["bb_std"]
        )
        rsi = calc_rsi(df, period=CONFIG["rsi_period"])
        macd = calc_macd(
            df,
            fast=CONFIG["macd_fast"],
            slow=CONFIG["macd_slow"],
            signal_period=CONFIG["macd_signal"],
        )
        vol = calc_volume_ratio(df, period=CONFIG["volume_period"])

        return {
            "bb": bb,
            "rsi": rsi,
            "macd": macd,
            "volume": vol,
        }
