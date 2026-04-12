import pandas as pd


def calc_volume_ratio(df: pd.DataFrame, period: int = 20) -> dict:
    """거래량 비율 계산.

    Args:
        df: 캔들 데이터 (volume 컬럼 필수)
        period: 평균 거래량 비교 기간

    Returns:
        current_volume, avg_volume, ratio
    """
    volume = df["volume"]
    avg_volume = volume.rolling(window=period).mean()
    current_volume = volume.iloc[-1]
    current_avg = avg_volume.iloc[-1]

    ratio = current_volume / current_avg if current_avg > 0 else 0.0

    return {
        "current_volume": current_volume,
        "avg_volume": current_avg,
        "ratio": ratio,
    }
