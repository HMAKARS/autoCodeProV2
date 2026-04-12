import pandas as pd


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI(Relative Strength Index) 계산.

    Args:
        df: 캔들 데이터 (close 컬럼 필수)
        period: RSI 기간

    Returns:
        RSI 시리즈 (0~100)
    """
    close = df["close"]
    delta = close.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    return rsi
