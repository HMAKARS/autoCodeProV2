import pandas as pd


def calc_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict:
    """MACD 계산.

    Args:
        df: 캔들 데이터 (close 컬럼 필수)
        fast: 단기 EMA 기간
        slow: 장기 EMA 기간
        signal_period: 시그널 기간

    Returns:
        macd, signal, histogram
    """
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }
