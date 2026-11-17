import logging
import os
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# 네이버 서버 접근 시 매너 명찰(헤더)
NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://stock.naver.com/",
}

REQUEST_TIMEOUT = 5


def validate_stock_code(code: Any) -> Optional[str]:
    """종목코드가 6자리 숫자인지 검증하고 오류 메시지를 반환한다."""
    if not code or not isinstance(code, str):
        return "종목코드가 입력되지 않았습니다."
    stripped = code.strip()
    if not re.fullmatch(r"\d{6}", stripped):
        return "종목코드는 6자리 숫자여야 합니다. (예: 000660)"
    return None


def clean_number(value: Any, as_float: bool = False) -> Optional[float | int]:
    """문자열 수치에서 콤마와 단위를 제거하고 순수 숫자로 변환한다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if as_float else int(value)

    text = str(value).strip()
    if not text or text in ("-", "N/A", "nan"):
        return None

    # 숫자, 소수점, 음수 부호만 추출
    cleaned = re.sub(r"[^\d.\-]", "", text)
    if not cleaned or cleaned in ("-", "."):
        return None

    try:
        num = float(cleaned)
        return num if as_float else int(round(num))
    except ValueError:
        return None


def parse_korean_amount(value: Any) -> Optional[int]:
    """'894조 8,531억' 같은 한국어 금액 단위를 원 단위 순수 정수로 변환한다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).replace(",", "").strip()
    if not text or text in ("-", "N/A"):
        return None

    total = 0
    matched = False

    jo_match = re.search(r"(\d+)\s*조", text)
    if jo_match:
        total += int(jo_match.group(1)) * 10**12
        matched = True

    eok_match = re.search(r"(\d+)\s*억", text)
    if eok_match:
        total += int(eok_match.group(1)) * 10**8
        matched = True

    man_match = re.search(r"(\d+)\s*만", text)
    if man_match:
        total += int(man_match.group(1)) * 10**4
        matched = True

    if matched:
        return total
    return clean_number(text, as_float=False)


def _request_naver_json(url: str, code: str, label: str) -> Dict[str, Any]:
    """네이버 금융 API 공통 GET 요청 및 오류 처리 헬퍼."""
    logger.info(f"[NAVER] 네이버 금융 {label} 접근 시작 (User-Agent 적용) - {url}")

    try:
        response = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        logger.error(f"[ERROR] 네이버 금융 {label} API 네트워크 타임아웃", exc_info=True)
        raise RuntimeError("네트워크 타임아웃이 발생했습니다. 잠시 후 다시 시도해 주세요.") from exc
    except requests.RequestException as exc:
        logger.error(f"[ERROR] 네이버 금융 {label} API 요청 실패", exc_info=True)
        raise RuntimeError("네이버 금융 서버에 연결할 수 없습니다.") from exc

    if response.status_code == 404:
        logger.error(f"[ERROR] 존재하지 않는 종목코드 또는 페이지 없음 (404): {code}")
        raise RuntimeError(f"종목코드({code})에 해당하는 종목을 찾을 수 없습니다. (404)")
    if response.status_code in (403, 429):
        logger.error(f"[ERROR] 네이버 금융 접근 차단 ({response.status_code}): {code}")
        raise RuntimeError("네이버 금융 서버에서 요청이 차단되었습니다. 잠시 후 다시 시도해 주세요.")
    if not response.ok:
        logger.error(f"[ERROR] 네이버 금융 응답 오류 ({response.status_code}): {code}")
        raise RuntimeError(f"네이버 금융 페이지 접근에 실패했습니다. (HTTP {response.status_code})")

    try:
        data = response.json()
    except ValueError as exc:
        logger.error(f"[ERROR] 네이버 금융 {label} API JSON 변환 실패", exc_info=True)
        raise RuntimeError("네이버 금융 응답 데이터를 JSON으로 변환하는 데 실패했습니다.") from exc

    if not isinstance(data, dict):
        logger.error(f"[ERROR] 네이버 금융 {label} API 데이터 구조 변경 감지")
        raise RuntimeError("네이버 금융 데이터 구조가 예상과 다릅니다.")

    return data


def fetch_basic_info(code: str) -> Dict[str, Any]:
    """네이버 금융 basic API에서 정식 종목명, 현재가, 등락률을 수집한다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"
    data = _request_naver_json(url, code, "basic")

    stock_name = data.get("stockName")
    if not stock_name or not str(stock_name).strip():
        logger.error(f"[ERROR] 종목명 파싱 실패: {code}")
        raise RuntimeError("정식 종목명을 파싱하지 못했습니다.")

    current_price = clean_number(data.get("closePrice"), as_float=False)
    change_rate = clean_number(data.get("fluctuationsRatio"), as_float=True)

    # 하락인데 부호가 빠진 경우 보정
    compare_info = data.get("compareToPreviousPrice") or {}
    if (
        isinstance(compare_info, dict)
        and compare_info.get("name") == "FALLING"
        and change_rate is not None
        and change_rate > 0
    ):
        change_rate = -change_rate

    logger.info(
        f"[PARSE] 기본 시세 파싱 완료 (name={stock_name}, current_price={current_price}, change_rate={change_rate})"
    )

    return {
        "code": code,
        "name": str(stock_name).strip(),
        "current_price": current_price,
        "change_rate": change_rate,
    }


def fetch_integration_info(code: str) -> Dict[str, Any]:
    """네이버 금융 integration API에서 시총, 52주 최고/최저, PER/PBR 등 투자정보를 수집한다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"
    data = _request_naver_json(url, code, "integration")

    total_infos = data.get("totalInfos")
    if not isinstance(total_infos, list):
        logger.error(f"[ERROR] integration totalInfos 구조 변경 감지: {code}")
        raise RuntimeError("네이버 금융 투자정보 데이터 구조가 예상과 다릅니다.")

    info_map = {
        item.get("code"): item.get("value")
        for item in total_infos
        if isinstance(item, dict) and item.get("code")
    }

    result = {
        "market_cap": parse_korean_amount(info_map.get("marketValue")),
        "high_52w": clean_number(info_map.get("highPriceOf52Weeks"), as_float=False),
        "low_52w": clean_number(info_map.get("lowPriceOf52Weeks"), as_float=False),
        "foreign_rate": clean_number(info_map.get("foreignRate"), as_float=True),
        "per": clean_number(info_map.get("per"), as_float=True),
        "cns_per": clean_number(info_map.get("cnsPer"), as_float=True),
        "pbr": clean_number(info_map.get("pbr"), as_float=True),
        "bps": clean_number(info_map.get("bps"), as_float=False),
        "dividend_yield": clean_number(info_map.get("dividendYieldRatio"), as_float=True),
    }

    logger.info(
        f"[PARSE] 투자정보 파싱 완료 (code={code}, market_cap={result['market_cap']}, per={result['per']}, pbr={result['pbr']})"
    )
    return result


def fetch_financials(code: str, period_type: str = "annual") -> List[Dict[str, Any]]:
    """네이버 금융 finance API에서 연간/분기 실적 및 추정치(is_consensus)를 수집한다."""
    url = f"https://m.stock.naver.com/api/stock/{code}/finance/{period_type}"
    data = _request_naver_json(url, code, f"finance/{period_type}")

    finance_info = data.get("financeInfo")
    if not isinstance(finance_info, dict):
        logger.error(f"[ERROR] financeInfo 구조 변경 감지: {code}")
        raise RuntimeError("네이버 금융 실적 데이터 구조가 예상과 다릅니다.")

    tr_title_list = finance_info.get("trTitleList") or []
    row_list = finance_info.get("rowList") or []
    if not isinstance(tr_title_list, list) or not isinstance(row_list, list):
        logger.error(f"[ERROR] financeInfo 리스트 구조 변경 감지: {code}")
        raise RuntimeError("네이버 금융 실적 표 구조가 예상과 다릅니다.")

    # 항목명 -> {기간키: 값} 맵 구성
    row_map: Dict[str, Dict[str, Any]] = {}
    for row in row_list:
        if isinstance(row, dict) and row.get("title"):
            row_map[row["title"].strip()] = row.get("columns") or {}

    def _get_cell_value(metric_name: str, period_key: str) -> Any:
        col_data = row_map.get(metric_name, {}).get(period_key)
        if isinstance(col_data, dict):
            return col_data.get("value")
        return None

    financials: List[Dict[str, Any]] = []
    for col in tr_title_list:
        if not isinstance(col, dict):
            continue
        period_key = col.get("key")
        raw_title = str(col.get("title", "")).strip()
        if not period_key or not raw_title:
            continue

        # "2024.12." -> "2024.12"
        period = raw_title.rstrip(".")
        is_consensus = col.get("isConsensus") == "Y"

        # 매출액, 영업이익은 네이버 표 기준 '억원' 단위이므로 원 단위로 변환
        rev_eok = clean_number(_get_cell_value("매출액", period_key), as_float=False)
        op_eok = clean_number(_get_cell_value("영업이익", period_key), as_float=False)

        financials.append({
            "period": period,
            "period_type": period_type,
            "is_consensus": is_consensus,
            "revenue": rev_eok * 10**8 if rev_eok is not None else None,
            "operating_income": op_eok * 10**8 if op_eok is not None else None,
            "operating_margin": clean_number(_get_cell_value("영업이익률", period_key), as_float=True),
            "roe": clean_number(_get_cell_value("ROE", period_key), as_float=True),
            "debt_ratio": clean_number(_get_cell_value("부채비율", period_key), as_float=True),
            "reserve_ratio": clean_number(_get_cell_value("유보율", period_key), as_float=True),
        })

    logger.info(f"[PARSE] 기업실적 파싱 완료 (code={code}, period_type={period_type}, count={len(financials)})")
    return financials


def fetch_news(stock_name: str, num: int = 5) -> List[Dict[str, str]]:
    """네이버에서 파싱한 정식 종목명으로 Serper News API를 호출하여 최신 뉴스를 수집한다."""
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        logger.error("[ERROR] Serper API Key 미설정")
        raise RuntimeError("Serper API Key가 설정되지 않았습니다. (.env 파일을 확인해 주세요)")

    url = "https://google.serper.dev/news"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": stock_name,
        "gl": "kr",
        "hl": "ko",
        "num": num,
    }

    logger.info(f"[SERPER] Serper News API 호출 시작 (query={stock_name})")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        logger.error("[ERROR] Serper News API 네트워크 타임아웃", exc_info=True)
        raise RuntimeError("뉴스 검색 API 요청 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        logger.error("[ERROR] Serper News API 요청 실패", exc_info=True)
        raise RuntimeError("뉴스 검색 API 연결에 실패했습니다.") from exc

    if response.status_code in (401, 403):
        logger.error(f"[ERROR] Serper API 인증 실패 ({response.status_code})")
        raise RuntimeError("Serper API 인증에 실패했습니다. API Key를 확인해 주세요.")
    if not response.ok:
        logger.error(f"[ERROR] Serper API 호출 실패 (HTTP {response.status_code})")
        raise RuntimeError(f"Serper News API 호출에 실패했습니다. (HTTP {response.status_code})")

    try:
        data = response.json()
    except ValueError as exc:
        logger.error("[ERROR] Serper API 응답 JSON 변환 실패", exc_info=True)
        raise RuntimeError("뉴스 검색 응답 데이터를 JSON으로 변환하는 데 실패했습니다.") from exc

    raw_news = data.get("news")
    if not isinstance(raw_news, list):
        logger.warning(f"[SERPER] 뉴스 검색 결과 없음 또는 구조 상이 (query={stock_name})")
        return []

    articles: List[Dict[str, str]] = []
    for item in raw_news[:num]:
        if not isinstance(item, dict):
            continue
        articles.append({
            "title": str(item.get("title", "")).strip(),
            "url": str(item.get("link", "")).strip(),
            "description": str(item.get("snippet", "")).strip(),
            "published": str(item.get("date", "")).strip(),
        })

    logger.info(f"[SERPER] 뉴스 수집 완료 (query={stock_name}, count={len(articles)})")
    return articles


def collect_stock_data(code: str) -> Dict[str, Any]:
    """종목코드를 받아 시세, 투자정보, 실적, 뉴스를 통합 수집하고 영역별 오류를 격리한다."""
    errors: List[Dict[str, str]] = []

    # 1. 기본 시세 및 정식 종목명 (필수 선행 작업)
    basic = fetch_basic_info(code)
    stock_name = basic["name"]

    snapshot: Dict[str, Any] = {
        "current_price": basic["current_price"],
        "change_rate": basic["change_rate"],
    }

    # 2. 투자정보 (실패 시 errors에 기록하고 계속 진행)
    try:
        integ = fetch_integration_info(code)
        snapshot.update(integ)
    except RuntimeError as exc:
        errors.append({"section": "snapshot_detail", "message": str(exc)})

    # 3. 기업실적분석 연간 (실패 시 errors에 기록하고 계속 진행)
    financials: List[Dict[str, Any]] = []
    try:
        financials = fetch_financials(code, period_type="annual")
    except RuntimeError as exc:
        errors.append({"section": "financials", "message": str(exc)})

    # 4. Serper 뉴스 (파싱한 정식 종목명으로 조회, 실패 시 errors에 기록하고 계속 진행)
    news: List[Dict[str, str]] = []
    try:
        news = fetch_news(stock_name, num=5)
    except RuntimeError as exc:
        errors.append({"section": "news", "message": str(exc)})

    return {
        "code": code,
        "name": stock_name,
        "snapshot": snapshot,
        "financials": financials,
        "news": news,
        "errors": errors,
    }
