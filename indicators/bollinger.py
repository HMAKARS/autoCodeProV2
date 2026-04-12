import pandas as pd


def calc_bollinger(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> dict:
    """볼린저밴드 계산.

    Args:
        df: 캔들 데이터 (close 컬럼 필수)
        period: 이동평균 기간
        std: 표준편차 배수

    Returns:
        upper, middle, lower, percent_b, bandwidth
    """
    close = df["close"]
    middle = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()

    upper = middle + (rolling_std * std)
    lower = middle - (rolling_std * std)

    band_diff = upper - lower
    percent_b = (close - lower) / band_diff.replace(0, float("nan"))
    bandwidth = band_diff / middle.replace(0, float("nan"))

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "percent_b": percent_b,
        "bandwidth": bandwidth,
    }
