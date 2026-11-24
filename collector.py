import logging
import os
import re
import urllib.parse
from datetime import datetime
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


def is_us_ticker(code: str) -> bool:
    """미국 주식/ETF 티커(영문 1~5자 또는 AAPL.O 형식)인지 판별한다."""
    return bool(re.fullmatch(r"[A-Za-z]{1,5}(?:\.[A-Za-z]{1,2})?", code.strip()))


def validate_stock_code(code: Any) -> Optional[str]:
    """입력값이 비어있지 않은지 검증한다. (종목명, 6자리 코드, 미국 티커 모두 허용)"""
    if not code or not isinstance(code, str) or not code.strip():
        return "종목명 또는 종목코드를 입력해 주세요."
    return None


def search_stocks(query: str, limit: int = 6) -> List[Dict[str, str]]:
    """네이버 자동완성 API를 통해 종목명/코드/티커 검색 결과 목록(국내·미국)을 반환한다."""
    q = str(query or "").strip()
    if not q:
        return []

    url = f"https://ac.stock.naver.com/ac?q={urllib.parse.quote(q)}&target=stock"
    try:
        res = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
        if not res.ok:
            return []
        data = res.json()
    except Exception:
        return []

    items = data.get("items") or []
    results: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nation = str(item.get("nationCode", "")).upper()
        if nation not in ("KOR", "USA"):
            continue
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        if not code or not name:
            continue
        results.append({
            "code": code,
            "reuters_code": str(item.get("reutersCode") or code).strip(),
            "name": name,
            "nation": nation,
            "exchange": str(item.get("typeName") or item.get("typeCode") or "").strip(),
        })
        if len(results) >= limit:
            break
    return results


def resolve_stock_code(raw_input: str) -> str:
    """사용자가 입력한 종목명('애플', '삼성전자') 또는 코드('000660', 'AAPL')를 표준 종목코드로 변환한다."""
    text = str(raw_input or "").strip()
    if not text:
        raise RuntimeError("종목명 또는 종목코드를 입력해 주세요.")

    if re.fullmatch(r"\d{6}", text):
        return text
    if is_us_ticker(text):
        return text.upper()

    matches = search_stocks(text, limit=5)
    if not matches:
        raise RuntimeError(f"'{text}'에 해당하는 국내/미국 종목을 찾을 수 없습니다.")

    # 정확히 일치하는 이름이 있으면 우선 선택
    lowered = text.lower()
    for m in matches:
        if m["name"].lower() == lowered:
            return m["code"]
    return matches[0]["code"]


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
        "stock_type": str(data.get("stockEndType", "stock")).lower(),
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

    etf_raw = data.get("etfKeyIndicator") or {}
    market_cap = parse_korean_amount(info_map.get("marketValue"))
    if market_cap is None and isinstance(etf_raw, dict):
        market_cap = parse_korean_amount(etf_raw.get("marketValue"))

    dividend_yield = clean_number(info_map.get("dividendYieldRatio"), as_float=True)
    if dividend_yield is None and isinstance(etf_raw, dict):
        dividend_yield = clean_number(etf_raw.get("dividendYieldTtm"), as_float=True)

    result = {
        "market_cap": market_cap,
        "high_52w": clean_number(info_map.get("highPriceOf52Weeks"), as_float=False),
        "low_52w": clean_number(info_map.get("lowPriceOf52Weeks"), as_float=False),
        "foreign_rate": clean_number(info_map.get("foreignRate"), as_float=True),
        "per": clean_number(info_map.get("per"), as_float=True),
        "cns_per": clean_number(info_map.get("cnsPer"), as_float=True),
        "pbr": clean_number(info_map.get("pbr"), as_float=True),
        "bps": clean_number(info_map.get("bps"), as_float=False),
        "dividend_yield": dividend_yield,
    }

    if isinstance(etf_raw, dict) and etf_raw:
        result["etf_info"] = {
            "issuer": etf_raw.get("issuerName"),
            "nav": clean_number(etf_raw.get("nav"), as_float=True),
            "total_fee_pct": clean_number(etf_raw.get("totalFee"), as_float=True),
            "deviation_rate_pct": clean_number(etf_raw.get("deviationRate"), as_float=True),
            "return_1m_pct": clean_number(etf_raw.get("returnRate1m"), as_float=True),
            "return_3m_pct": clean_number(etf_raw.get("returnRate3m"), as_float=True),
            "return_1y_pct": clean_number(etf_raw.get("returnRate1y"), as_float=True),
        }

    # 증권사 컨센서스 (목표주가, 투자의견)
    cons_raw = data.get("consensusInfo") or {}
    consensus = None
    if isinstance(cons_raw, dict) and (cons_raw.get("priceTargetMean") or cons_raw.get("recommMean")):
        consensus = {
            "target_price": clean_number(cons_raw.get("priceTargetMean"), as_float=False),
            "opinion_score": clean_number(cons_raw.get("recommMean"), as_float=True),
            "updated_at": str(cons_raw.get("createDate", "")).strip(),
        }

    # 최근 5거래일 외국인·기관·개인 수급 동향
    deals_raw = data.get("dealTrendInfos") or []
    investor_trend: List[Dict[str, Any]] = []
    if isinstance(deals_raw, list):
        for d in deals_raw[:5]:
            if not isinstance(d, dict):
                continue
            investor_trend.append({
                "date": str(d.get("bizdate", "")).strip(),
                "close_price": clean_number(d.get("closePrice"), as_float=False),
                "foreigner_net": clean_number(d.get("foreignerPureBuyQuant"), as_float=False),
                "organ_net": clean_number(d.get("organPureBuyQuant"), as_float=False),
                "individual_net": clean_number(d.get("individualPureBuyQuant"), as_float=False),
            })

    # 동종 업종 경쟁사 비교 (최대 4개)
    peers_raw = data.get("industryCompareInfo") or []
    peers: List[Dict[str, Any]] = []
    if isinstance(peers_raw, list):
        for p in peers_raw[:4]:
            if not isinstance(p, dict) or not p.get("stockName"):
                continue
            p_rate = clean_number(p.get("fluctuationsRatio"), as_float=True)
            p_cmp = p.get("compareToPreviousPrice") or {}
            if isinstance(p_cmp, dict) and p_cmp.get("name") == "FALLING" and p_rate and p_rate > 0:
                p_rate = -p_rate
            peers.append({
                "code": str(p.get("itemCode", "")).strip(),
                "name": str(p.get("stockName", "")).strip(),
                "current_price": clean_number(p.get("closePrice"), as_float=False),
                "change_rate": p_rate,
            })

    # 증권사 최신 리포트 (최대 5건)
    res_raw = data.get("researches") or []
    researches: List[Dict[str, str]] = []
    if isinstance(res_raw, list):
        for r in res_raw[:5]:
            if not isinstance(r, dict) or not r.get("tit"):
                continue
            researches.append({
                "broker": str(r.get("bnm", "")).strip(),
                "title": str(r.get("tit", "")).strip(),
                "date": str(r.get("wdt", "")).strip(),
            })

    result["_extra"] = {
        "consensus": consensus,
        "investor_trend": investor_trend,
        "peers": peers,
        "researches": researches,
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


def _resolve_us_reuters_code(ticker: str) -> str:
    """네이버 자동완성 API로 미국 티커(예: AAPL)의 정확한 reutersCode(예: AAPL.O)를 찾는다."""
    upper_ticker = ticker.strip().upper()
    if "." in upper_ticker:
        return upper_ticker

    ac_url = f"https://ac.stock.naver.com/ac?q={upper_ticker}&target=stock"
    data = _request_naver_json(ac_url, upper_ticker, "us-search")
    items = data.get("items") or []

    usa_items = [
        item for item in items
        if isinstance(item, dict) and item.get("nationCode") == "USA"
    ]
    for item in usa_items:
        if str(item.get("code", "")).upper() == upper_ticker and item.get("reutersCode"):
            return str(item["reutersCode"])
    if usa_items and usa_items[0].get("reutersCode"):
        return str(usa_items[0]["reutersCode"])

    raise RuntimeError(f"미국 종목 티커({upper_ticker})를 네이버 증권에서 찾을 수 없습니다.")


def _parse_us_finance_rows(fin_data: Dict[str, Any], period_type: str) -> List[Dict[str, Any]]:
    """네이버 해외주식 finance 응답(원화 환산 krw 억원 기준)을 표준 실적 리스트로 변환한다."""
    tr_title_list = fin_data.get("trTitleList") or []
    row_list = fin_data.get("rowList") or []
    if not isinstance(tr_title_list, list) or not isinstance(row_list, list):
        return []

    row_map: Dict[str, Dict[str, Any]] = {}
    for row in row_list:
        if isinstance(row, dict) and row.get("title"):
            row_map[row["title"].strip()] = row.get("columns") or {}

    def _get_cell(metric_name: str, key: str, use_krw: bool = False) -> Any:
        cell = row_map.get(metric_name, {}).get(key)
        if isinstance(cell, dict):
            return cell.get("krw") if use_krw and cell.get("krw") else cell.get("value")
        return None

    results: List[Dict[str, Any]] = []
    for col in tr_title_list:
        if not isinstance(col, dict):
            continue
        key = col.get("key")
        title = str(col.get("title", "")).strip()
        if not key or not title:
            continue

        rev_krw_eok = clean_number(_get_cell("매출액", key, use_krw=True), as_float=True)
        op_krw_eok = clean_number(_get_cell("영업이익", key, use_krw=True), as_float=True)

        results.append({
            "period": title[:7] if len(title) >= 7 else title,
            "period_type": period_type,
            "is_consensus": col.get("isConsensus") == "Y",
            "revenue": int(round(rev_krw_eok * 10**8)) if rev_krw_eok is not None else None,
            "operating_income": int(round(op_krw_eok * 10**8)) if op_krw_eok is not None else None,
            "operating_margin": clean_number(_get_cell("영업이익률", key), as_float=True),
            "roe": clean_number(_get_cell("ROE", key), as_float=True),
            "debt_ratio": clean_number(_get_cell("부채비율", key), as_float=True),
            "reserve_ratio": clean_number(_get_cell("유보율", key), as_float=True),
        })
    return results


def _collect_us_stock_data(ticker: str) -> Dict[str, Any]:
    """미국 주식/ETF 데이터를 네이버 해외주식 API + Serper 뉴스에서 수집한다."""
    errors: List[Dict[str, str]] = []
    upper_ticker = ticker.strip().upper()
    reuters_code = _resolve_us_reuters_code(upper_ticker)

    # 1. 기본 시세 + 스냅샷
    basic_url = f"https://api.stock.naver.com/stock/{reuters_code}/basic"
    basic = _request_naver_json(basic_url, upper_ticker, "us-basic")

    stock_name = str(basic.get("stockName") or upper_ticker).strip()
    stock_name_eng = str(basic.get("stockNameEng") or "").strip()
    stock_type = "etf" if basic.get("isEtf") or basic.get("isEtfAmerica") else str(basic.get("stockEndType", "stock")).lower()

    current_price = clean_number(basic.get("closePriceRaw") or basic.get("closePrice"), as_float=True)
    change_rate = clean_number(basic.get("fluctuationsRatioRaw") or basic.get("fluctuationsRatio"), as_float=True)
    cmp_info = basic.get("compareToPreviousPrice") or {}
    if isinstance(cmp_info, dict) and cmp_info.get("name") == "FALLING" and change_rate and change_rate > 0:
        change_rate = -change_rate

    info_map = {
        item.get("code"): item.get("value")
        for item in (basic.get("stockItemTotalInfos") or [])
        if isinstance(item, dict) and item.get("code")
    }

    snapshot: Dict[str, Any] = {
        "current_price": current_price,
        "change_rate": change_rate,
        "market_cap": clean_number(basic.get("marketValueKrwRaw"), as_float=False),
        "high_52w": clean_number(info_map.get("highPriceOf52Weeks"), as_float=True),
        "low_52w": clean_number(info_map.get("lowPriceOf52Weeks"), as_float=True),
        "foreign_rate": None,
        "per": clean_number(info_map.get("per"), as_float=True),
        "cns_per": None,
        "pbr": clean_number(info_map.get("pbr"), as_float=True),
        "bps": clean_number(info_map.get("bps"), as_float=True),
        "dividend_yield": clean_number(info_map.get("dividendYieldRatio"), as_float=True),
    }

    # 2. 컨센서스, 경쟁사, 리포트
    consensus = None
    peers: List[Dict[str, Any]] = []
    researches: List[Dict[str, str]] = []
    try:
        integ_url = f"https://api.stock.naver.com/stock/{reuters_code}/integration"
        integ = _request_naver_json(integ_url, upper_ticker, "us-integration")

        cons_raw = integ.get("consensusInfo") or {}
        if isinstance(cons_raw, dict) and (cons_raw.get("priceTargetMean") or cons_raw.get("recommMean")):
            target_p = clean_number(cons_raw.get("priceTargetMean"), as_float=True)
            upside = round((target_p - current_price) / current_price * 100, 1) if (target_p and current_price) else None
            consensus = {
                "target_price": target_p,
                "opinion_score": clean_number(cons_raw.get("recommMean"), as_float=True),
                "upside_pct": upside,
                "updated_at": str(cons_raw.get("createDate", "")).strip(),
            }

        global_peers = (integ.get("industryCompareInfo") or {}).get("globalStocks") or []
        for p in global_peers[:4]:
            if not isinstance(p, dict) or not p.get("stockName"):
                continue
            p_rate = clean_number(p.get("fluctuationsRatio"), as_float=True)
            p_cmp = p.get("compareToPreviousPrice") or {}
            if isinstance(p_cmp, dict) and p_cmp.get("name") == "FALLING" and p_rate and p_rate > 0:
                p_rate = -p_rate
            peers.append({
                "code": str(p.get("symbolCode") or p.get("reutersCode") or "").strip(),
                "name": str(p.get("stockName", "")).strip(),
                "current_price": clean_number(p.get("closePrice"), as_float=True),
                "change_rate": p_rate,
            })

        for r in (integ.get("reports") or [])[:5]:
            if isinstance(r, dict) and r.get("title"):
                researches.append({
                    "broker": str(r.get("brokerName") or r.get("writer") or "리서치").strip(),
                    "title": str(r.get("title", "")).strip(),
                    "date": str(r.get("writeDate", "")).strip(),
                })
    except RuntimeError as exc:
        errors.append({"section": "snapshot_detail", "message": str(exc)})

    # 3. 연간 & 분기 실적 (ETF 제외)
    financials: List[Dict[str, Any]] = []
    quarterly_financials: List[Dict[str, Any]] = []
    if stock_type != "etf":
        try:
            fin_ann = _request_naver_json(f"https://api.stock.naver.com/stock/{reuters_code}/finance/annual", upper_ticker, "us-annual")
            financials = _parse_us_finance_rows(fin_ann, "annual")
        except RuntimeError as exc:
            errors.append({"section": "financials", "message": str(exc)})

        try:
            fin_q = _request_naver_json(f"https://api.stock.naver.com/stock/{reuters_code}/finance/quarter", upper_ticker, "us-quarter")
            quarterly_financials = _parse_us_finance_rows(fin_q, "quarter")[-4:]
        except RuntimeError:
            quarterly_financials = []

    # 4. Serper 뉴스 (한글 종목명 + 티커로 정밀 검색)
    news: List[Dict[str, str]] = []
    try:
        query_term = f"{stock_name} {upper_ticker}" if stock_name != upper_ticker else upper_ticker
        news = fetch_news(query_term, num=5)
    except RuntimeError as exc:
        errors.append({"section": "news", "message": str(exc)})

    display_name = f"{stock_name} ({stock_name_eng})" if stock_name_eng and stock_name_eng != stock_name else stock_name
    return {
        "code": upper_ticker.split(".")[0],
        "name": display_name,
        "stock_type": stock_type,
        "currency": "USD",
        "snapshot": snapshot,
        "consensus": consensus,
        "investor_trend": [],
        "peers": peers,
        "researches": researches,
        "financials": financials,
        "quarterly_financials": quarterly_financials,
        "news": news,
        "sources": {
            "market": f"네이버 증권 해외주식 ({basic.get('stockExchangeName', 'USA')}, stock.naver.com)",
            "financials": "네이버 증권 해외주식 실적 원화환산 (stock.naver.com)",
            "news": "Serper Google News (google.serper.dev)",
            "naver_url": f"https://stock.naver.com/worldstock/stock/{reuters_code}/total",
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "errors": errors,
    }


def collect_stock_data(code: str) -> Dict[str, Any]:
    """종목명 또는 코드를 받아 국내/미국 종목을 자동 판별하고 시세, 투자정보, 실적, 뉴스를 통합 수집한다."""
    cleaned_code = resolve_stock_code(code)
    if is_us_ticker(cleaned_code):
        return _collect_us_stock_data(cleaned_code)

    code = cleaned_code
    errors: List[Dict[str, str]] = []

    # 1. 기본 시세 및 정식 종목명 (필수 선행 작업)
    basic = fetch_basic_info(code)
    stock_name = basic["name"]
    stock_type = basic.get("stock_type", "stock")

    snapshot: Dict[str, Any] = {
        "current_price": basic["current_price"],
        "change_rate": basic["change_rate"],
    }

    # 2. 투자정보 + 컨센서스/수급/업종/리포트 (실패 시 errors에 기록하고 계속 진행)
    extra: Dict[str, Any] = {
        "consensus": None,
        "investor_trend": [],
        "peers": [],
        "researches": [],
    }
    try:
        integ = fetch_integration_info(code)
        extracted_extra = integ.pop("_extra", None)
        if isinstance(extracted_extra, dict):
            extra.update(extracted_extra)
        snapshot.update(integ)
    except RuntimeError as exc:
        errors.append({"section": "snapshot_detail", "message": str(exc)})

    # 목표주가 상승여력(%) 계산
    if extra["consensus"] and extra["consensus"].get("target_price") and snapshot.get("current_price"):
        target_p = extra["consensus"]["target_price"]
        curr_p = snapshot["current_price"]
        if curr_p > 0:
            extra["consensus"]["upside_pct"] = round((target_p - curr_p) / curr_p * 100, 1)

    # 3. 기업실적분석 연간 & 분기 (ETF는 재무제표가 없으므로 생략)
    financials: List[Dict[str, Any]] = []
    quarterly_financials: List[Dict[str, Any]] = []
    if stock_type != "etf":
        try:
            financials = fetch_financials(code, period_type="annual")
        except RuntimeError as exc:
            errors.append({"section": "financials", "message": str(exc)})

        try:
            quarterly_financials = fetch_financials(code, period_type="quarter")[-4:]
        except RuntimeError:
            # 분기 실적은 보조 데이터이므로 실패해도 치명적 오류로 노출하지 않음
            quarterly_financials = []

    # 4. Serper 뉴스 (파싱한 정식 종목명으로 조회, 실패 시 errors에 기록하고 계속 진행)
    news: List[Dict[str, str]] = []
    try:
        news = fetch_news(stock_name, num=5)
    except RuntimeError as exc:
        errors.append({"section": "news", "message": str(exc)})

    return {
        "code": code,
        "name": stock_name,
        "stock_type": stock_type,
        "currency": "KRW",
        "snapshot": snapshot,
        "consensus": extra["consensus"],
        "investor_trend": extra["investor_trend"],
        "peers": extra["peers"],
        "researches": extra["researches"],
        "financials": financials,
        "quarterly_financials": quarterly_financials,
        "news": news,
        "sources": {
            "market": "네이버 증권 시세·투자정보·수급·컨센서스 (stock.naver.com)",
            "financials": "네이버 증권 기업실적분석 연간/분기 (stock.naver.com)",
            "news": "Serper Google News (google.serper.dev)",
            "naver_url": f"https://stock.naver.com/domestic/stock/{code}/price",
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "errors": errors,
    }
