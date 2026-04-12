"""기술적 지표 계산 모듈."""

import pandas as pd


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """RSI (상대강도지수) 계산."""
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def calculate_macd(
    df: pd.DataFrame, short: int = 12, long: int = 26, signal: int = 9
) -> dict:
    """MACD 계산. 반환: macd, signal, histogram 최신값."""
    close = df["close"]
    ema_short = close.ewm(span=short, adjust=False).mean()
    ema_long = close.ewm(span=long, adjust=False).mean()
    macd_line = ema_short - ema_long
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
    }


def calculate_stochastic(df: pd.DataFrame, period: int = 14) -> dict:
    """스토캐스틱 K, D 계산."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    lowest = low.rolling(window=period).min()
    highest = high.rolling(window=period).max()
    denom = (highest - lowest).replace(0, float("nan"))
    k = ((close - lowest) / denom) * 100
    d = k.rolling(window=3).mean()
    return {
        "k": float(k.iloc[-1]),
        "d": float(d.iloc[-1]),
    }


def calculate_ema(df: pd.DataFrame, period: int) -> float:
    """지수이동평균(EMA) 최신값."""
    return float(df["close"].ewm(span=period, adjust=False).mean().iloc[-1])


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20) -> dict:
    """볼린저밴드 계산."""
    close = df["close"]
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + (std * 2)
    lower = middle - (std * 2)
    return {
        "upper": float(upper.iloc[-1]),
        "middle": float(middle.iloc[-1]),
        "lower": float(lower.iloc[-1]),
    }


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """ATR (평균진폭) 계산."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return float(atr.iloc[-1])
