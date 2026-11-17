import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import FinanceDataReader as fdr
import pandas as pd

logger = logging.getLogger(__name__)

MIN_TECH_DAYS = 30


def _to_clean_list(series: pd.Series, decimals: int = 2) -> List[Optional[float]]:
    """Pandas Series의 NaN을 None으로 변환하고 소수점을 반올림해 리스트로 반환한다."""
    result: List[Optional[float]] = []
    for val in series:
        if pd.isna(val):
            result.append(None)
        else:
            result.append(round(float(val), decimals))
    return result


def calculate_technical_indicators(code: str, lookback_days: int = 365, display_bars: int = 120) -> Dict[str, Any]:
    """FinanceDataReader 주가 데이터를 기반으로 MA(5/20/60), RSI(14), MACD, 볼린저밴드를 계산한다."""
    clean_code = str(code or "").strip().upper()
    if not clean_code:
        raise ValueError("종목코드를 입력해 주세요.")

    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    logger.info(f"[FDR] FinanceDataReader 기술지표 조회 시작 (code={clean_code}, start={start_str}, end={end_str})")
    try:
        df = fdr.DataReader(clean_code, start_str, end_str)
    except Exception as exc:
        logger.error(f"[ERROR] FinanceDataReader 조회 실패 (code={clean_code})", exc_info=True)
        raise RuntimeError(f"종목({clean_code})의 주가 데이터를 조회하지 못했습니다.") from exc

    if df is None or df.empty or "Close" not in df.columns:
        logger.warning(f"[FDR] 주가 데이터 없음 (code={clean_code})")
        raise RuntimeError(f"종목({clean_code})에 대한 주가 데이터가 존재하지 않습니다.")

    df = df.copy()
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Close"]).sort_index()

    if len(df) < MIN_TECH_DAYS:
        raise RuntimeError(
            f"종목({clean_code})의 거래일 수({len(df)}일)가 부족하여 기술지표를 계산할 수 없습니다."
        )

    logger.info(f"[FDR] FinanceDataReader 기술지표 조회 완료 (code={clean_code}, rows={len(df)})")

    close = df["Close"]

    # 1. 이동평균선 (MA5, MA20, MA60)
    df["MA5"] = close.rolling(window=5).mean()
    df["MA20"] = close.rolling(window=20).mean()
    df["MA60"] = close.rolling(window=60).mean()

    # 2. RSI (14, Wilder 방식 EMA)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI14"] = 100.0 - (100.0 / (1.0 + rs))
    # 하락이 0인 극단적 상승 구간은 RSI 100으로 처리
    df.loc[avg_loss == 0, "RSI14"] = 100.0

    # 3. MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    # 4. 볼린저밴드 (20, 2)
    bb_std = close.rolling(window=20).std()
    df["BB_MID"] = df["MA20"]
    df["BB_UPPER"] = df["BB_MID"] + (2.0 * bb_std)
    df["BB_LOWER"] = df["BB_MID"] - (2.0 * bb_std)

    # 차트 표시용 최근 N거래일 슬라이싱
    view_df = df.tail(display_bars)
    dates = [idx.strftime("%Y-%m-%d") for idx in view_df.index]

    last_row = view_df.iloc[-1]
    latest = {
        "date": dates[-1],
        "close": round(float(last_row["Close"]), 2),
        "ma5": None if pd.isna(last_row["MA5"]) else round(float(last_row["MA5"]), 2),
        "ma20": None if pd.isna(last_row["MA20"]) else round(float(last_row["MA20"]), 2),
        "ma60": None if pd.isna(last_row["MA60"]) else round(float(last_row["MA60"]), 2),
        "rsi14": None if pd.isna(last_row["RSI14"]) else round(float(last_row["RSI14"]), 2),
        "macd": None if pd.isna(last_row["MACD"]) else round(float(last_row["MACD"]), 2),
        "macd_signal": None if pd.isna(last_row["MACD_SIGNAL"]) else round(float(last_row["MACD_SIGNAL"]), 2),
        "macd_hist": None if pd.isna(last_row["MACD_HIST"]) else round(float(last_row["MACD_HIST"]), 2),
        "bb_upper": None if pd.isna(last_row["BB_UPPER"]) else round(float(last_row["BB_UPPER"]), 2),
        "bb_mid": None if pd.isna(last_row["BB_MID"]) else round(float(last_row["BB_MID"]), 2),
        "bb_lower": None if pd.isna(last_row["BB_LOWER"]) else round(float(last_row["BB_LOWER"]), 2),
    }

    series = {
        "dates": dates,
        "close": _to_clean_list(view_df["Close"], 2),
        "ma5": _to_clean_list(view_df["MA5"], 2),
        "ma20": _to_clean_list(view_df["MA20"], 2),
        "ma60": _to_clean_list(view_df["MA60"], 2),
        "rsi14": _to_clean_list(view_df["RSI14"], 2),
        "macd": _to_clean_list(view_df["MACD"], 2),
        "macd_signal": _to_clean_list(view_df["MACD_SIGNAL"], 2),
        "macd_hist": _to_clean_list(view_df["MACD_HIST"], 2),
        "bb_upper": _to_clean_list(view_df["BB_UPPER"], 2),
        "bb_lower": _to_clean_list(view_df["BB_LOWER"], 2),
    }

    logger.info(
        f"[CALC] 기술지표 계산 완료 (code={clean_code}, date={latest['date']}, rsi14={latest['rsi14']}, macd={latest['macd']})"
    )

    return {
        "code": clean_code,
        "latest": latest,
        "series": series,
    }
