import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_TRADING_DAYS = 60
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.035


def validate_portfolio_codes(raw_codes: List[str]) -> List[str]:
    """입력된 종목/ETF 코드 리스트를 정제하고 2개 이상인지 검증한다."""
    cleaned: List[str] = []
    seen = set()
    for code in raw_codes:
        c = str(code).strip().upper()
        if c and c not in seen:
            cleaned.append(c)
            seen.add(c)

    if len(cleaned) < 2:
        raise ValueError("리밸런싱을 계산하려면 서로 다른 종목/ETF 코드를 2개 이상 입력해 주세요.")
    if len(cleaned) > 10:
        raise ValueError("안정적인 시뮬레이션을 위해 종목은 최대 10개까지 입력할 수 있습니다.")
    return cleaned


def fetch_price_dataframe(codes: List[str], days: int = 365) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """FinanceDataReader로 최근 1년(365일) 일별 종가와 일별 수익률 DataFrame을 수집·정제한다."""
    end_dt = datetime.today()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    series_map: Dict[str, pd.Series] = {}

    for code in codes:
        logger.info(f"[FDR] FinanceDataReader 데이터 조회 시작 (code={code}, start={start_str}, end={end_str})")
        try:
            df = fdr.DataReader(code, start_str, end_str)
        except Exception as exc:
            logger.error(f"[ERROR] FinanceDataReader 조회 실패 (code={code})", exc_info=True)
            raise RuntimeError(f"종목({code})의 주가 데이터를 조회하지 못했습니다.") from exc

        if df is None or df.empty or "Close" not in df.columns:
            logger.warning(f"[FDR] 주가 데이터 없음 (code={code})")
            raise RuntimeError(f"종목({code})에 대한 주가 데이터가 존재하지 않습니다.")

        close_series = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(close_series) < MIN_TRADING_DAYS:
            raise RuntimeError(
                f"종목({code})의 최근 1년 거래일 수({len(close_series)}일)가 부족하여 계산할 수 없습니다."
            )

        series_map[code] = close_series
        logger.info(f"[FDR] FinanceDataReader 데이터 조회 완료 (code={code}, rows={len(close_series)})")

    # 날짜 기준 병합 및 결측치 정제 (전일 종가로 보간 후 남은 초기 결측 제거)
    prices_df = pd.concat(series_map, axis=1).sort_index()
    prices_df = prices_df.ffill().dropna()

    if len(prices_df) < MIN_TRADING_DAYS:
        raise RuntimeError("종목 간 공통 거래일 수가 부족하여 포트폴리오를 계산할 수 없습니다.")

    returns_df = prices_df.pct_change().dropna()
    if returns_df.empty:
        raise RuntimeError("일별 수익률을 계산할 수 없습니다.")

    return prices_df, returns_df


def _calc_mdd_pct(daily_returns: pd.Series) -> float:
    """일별 수익률 시리즈로부터 최대 낙폭(MDD, %)을 계산한다."""
    cumulative = (1.0 + daily_returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative / running_max) - 1.0
    return round(float(drawdown.min()) * 100.0, 2)


def calculate_rebalancing(raw_codes: List[str], num_simulations: int = 3000) -> Dict[str, Any]:
    """단순화 몬테카를로 시뮬레이션과 효율적 프론티어로 적정 비중 및 MDD를 계산한다."""
    codes = validate_portfolio_codes(raw_codes)
    prices_df, returns_df = fetch_price_dataframe(codes)

    mean_returns = returns_df.mean().values * TRADING_DAYS_PER_YEAR
    cov_matrix = returns_df.cov().values * TRADING_DAYS_PER_YEAR

    if np.isnan(mean_returns).any() or np.isnan(cov_matrix).any():
        raise RuntimeError("수익률 또는 공분산 계산 중 유효하지 않은 값이 발생했습니다.")

    n_assets = len(codes)

    # 단순화 몬테카를로 시뮬레이션 (벡터 연산)
    weights_matrix = np.random.dirichlet(np.ones(n_assets), size=num_simulations)
    port_returns = weights_matrix @ mean_returns
    port_variances = np.einsum("ij,jk,ik->i", weights_matrix, cov_matrix, weights_matrix)

    if (port_variances <= 0).any():
        port_variances = np.maximum(port_variances, 1e-12)

    port_vols = np.sqrt(port_variances)
    sharpe_ratios = (port_returns - RISK_FREE_RATE) / port_vols

    max_sharpe_idx = int(np.argmax(sharpe_ratios))
    min_vol_idx = int(np.argmin(port_vols))

    def _build_portfolio_summary(weights: np.ndarray) -> Dict[str, Any]:
        ret = float(weights @ mean_returns)
        vol = float(np.sqrt(max(weights @ cov_matrix @ weights, 1e-12)))
        sharpe = float((ret - RISK_FREE_RATE) / vol)
        port_daily = returns_df.dot(weights)
        mdd = _calc_mdd_pct(port_daily)
        return {
            "weights": {code: round(float(w) * 100.0, 2) for code, w in zip(codes, weights)},
            "expected_return_pct": round(ret * 100.0, 2),
            "volatility_pct": round(vol * 100.0, 2),
            "sharpe_ratio": round(sharpe, 2),
            "mdd_pct": mdd,
        }

    max_sharpe_port = _build_portfolio_summary(weights_matrix[max_sharpe_idx])
    min_vol_port = _build_portfolio_summary(weights_matrix[min_vol_idx])
    equal_weights = np.full(n_assets, 1.0 / n_assets)
    equal_port = _build_portfolio_summary(equal_weights)

    # 개별 종목 1년 성과 요약 및 근거 생성
    asset_stats: List[Dict[str, Any]] = []
    for idx, code in enumerate(codes):
        ann_ret = round(float(mean_returns[idx]) * 100.0, 2)
        ann_vol = round(float(np.sqrt(max(cov_matrix[idx, idx], 0.0))) * 100.0, 2)
        mdd_single = _calc_mdd_pct(returns_df[code])
        asset_stats.append({
            "code": code,
            "annual_return_pct": ann_ret,
            "annual_volatility_pct": ann_vol,
            "mdd_pct": mdd_single,
            "recommended_weight_pct": max_sharpe_port["weights"][code],
        })

    # 차트 시각화용 프론티어 산점도 샘플 (최대 300점)
    sample_size = min(300, num_simulations)
    sample_indices = np.linspace(0, num_simulations - 1, sample_size, dtype=int)
    frontier_points = [
        {
            "volatility": round(float(port_vols[i]) * 100.0, 2),
            "return": round(float(port_returns[i]) * 100.0, 2),
            "sharpe": round(float(sharpe_ratios[i]), 2),
        }
        for i in sample_indices
    ]

    # Python 규칙 기반 선정 근거 생성
    best_code = max(asset_stats, key=lambda x: x["recommended_weight_pct"])["code"]
    rationale = (
        f"최근 {len(prices_df)}거래일 기준 {num_simulations:,}회 몬테카를로 시뮬레이션 결과, "
        f"동일 비중(기대수익 {equal_port['expected_return_pct']}%, 변동성 {equal_port['volatility_pct']}%, MDD {equal_port['mdd_pct']}%) 대비 "
        f"최대 샤프 포트폴리오는 위험 대비 수익 효율(샤프지수 {max_sharpe_port['sharpe_ratio']})이 가장 높습니다. "
        f"이 조합은 변동성 {max_sharpe_port['volatility_pct']}%, 기대수익 {max_sharpe_port['expected_return_pct']}%, MDD {max_sharpe_port['mdd_pct']}%를 기록하며 "
        f"가장 높은 비중({max_sharpe_port['weights'][best_code]}%)이 {best_code}에 배분되었습니다."
    )

    logger.info(
        f"[CALC] 몬테카를로 시뮬레이션 완료 (codes={codes}, max_sharpe_weights={max_sharpe_port['weights']})"
    )

    return {
        "codes": codes,
        "trading_days": int(len(prices_df)),
        "simulations": num_simulations,
        "risk_free_rate_pct": round(RISK_FREE_RATE * 100.0, 2),
        "max_sharpe": max_sharpe_port,
        "min_volatility": min_vol_port,
        "equal_weight": equal_port,
        "asset_stats": asset_stats,
        "frontier_points": frontier_points,
        "rationale": rationale,
        "source": {
            "provider": "FinanceDataReader (KRX/네이버 일별 종가)",
            "period": f"{prices_df.index[0].strftime('%Y-%m-%d')} ~ {prices_df.index[-1].strftime('%Y-%m-%d')}",
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
