import io
import json
import logging
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_TIMEOUT = 6
_CORP_MAP_CACHE: Dict[str, str] = {}
_BUNDLED_FILE = Path(__file__).resolve().parent / "dart_corp_map.json"
_CACHE_FILE = Path(tempfile.gettempdir()) / "dart_corp_map.json"


def _load_corp_map(api_key: str) -> Dict[str, str]:
    """상장사 6자리 종목코드 -> DART 8자리 고유번호(corp_code) 매핑 테이블을 로드/캐싱한다."""
    global _CORP_MAP_CACHE
    if _CORP_MAP_CACHE:
        return _CORP_MAP_CACHE

    # 1순위: 프로젝트에 내장된 78KB 매핑 파일 즉시 로드 (콜드 스타트 0.002초)
    if _BUNDLED_FILE.exists():
        try:
            bundled = json.loads(_BUNDLED_FILE.read_text(encoding="utf-8"))
            if isinstance(bundled, dict) and bundled:
                _CORP_MAP_CACHE = bundled
                return _CORP_MAP_CACHE
        except Exception:
            pass

    # 2순위: 임시 폴더 캐시(최근 7일 이내면 재사용)
    if _CACHE_FILE.exists():
        age_sec = datetime.now().timestamp() - _CACHE_FILE.stat().st_mtime
        if age_sec < 7 * 86400:
            try:
                cached = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached:
                    _CORP_MAP_CACHE = cached
                    return _CORP_MAP_CACHE
            except Exception:
                pass

    logger.info("[DART] Open DART 고유번호 목록(corpCode.xml) 다운로드 시작")
    url = f"{DART_BASE_URL}/corpCode.xml"
    res = requests.get(url, params={"crtfc_key": api_key}, timeout=15)
    if not res.ok:
        raise RuntimeError(f"Open DART 고유번호 목록 다운로드 실패 (HTTP {res.status_code})")

    # ZIP 압축 해제 및 XML 파싱 (상장 종목코드가 있는 기업만 추출)
    corp_map: Dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
        if not xml_names:
            raise RuntimeError("Open DART 고유번호 XML 파일을 찾을 수 없습니다.")
        with zf.open(xml_names[0]) as xf:
            root = ET.parse(xf).getroot()
            for node in root.findall("list"):
                stock_cd = (node.findtext("stock_code") or "").strip()
                corp_cd = (node.findtext("corp_code") or "").strip()
                if stock_cd and corp_cd:
                    corp_map[stock_cd] = corp_cd

    if not corp_map:
        raise RuntimeError("Open DART 고유번호 파싱 결과가 비어 있습니다.")

    _CORP_MAP_CACHE = corp_map
    try:
        _CACHE_FILE.write_text(json.dumps(corp_map), encoding="utf-8")
    except Exception:
        pass

    logger.info(f"[DART] Open DART 고유번호 캐싱 완료 (상장사 {len(corp_map)}개)")
    return _CORP_MAP_CACHE


def fetch_dart_info(stock_code: str) -> Optional[Dict[str, Any]]:
    """Open DART에서 기업의 공식 개황 및 최근 3개월 공시 목록을 조회한다."""
    api_key = os.getenv("DART_API_KEY", "").strip()
    if not api_key:
        return None

    corp_map = _load_corp_map(api_key)
    corp_code = corp_map.get(stock_code)
    if not corp_code:
        logger.info(f"[DART] DART 고유번호 없음 (code={stock_code})")
        return None

    logger.info(f"[DART] Open DART 기업개황 및 공시 조회 시작 (code={stock_code}, corp_code={corp_code})")

    end_dt = datetime.today()
    bgn_dt = end_dt - timedelta(days=90)

    def _fetch_company() -> requests.Response:
        return requests.get(
            f"{DART_BASE_URL}/company.json",
            params={"crtfc_key": api_key, "corp_code": corp_code},
            timeout=DART_TIMEOUT,
        )

    def _fetch_list() -> requests.Response:
        return requests.get(
            f"{DART_BASE_URL}/list.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": bgn_dt.strftime("%Y%m%d"),
                "end_de": end_dt.strftime("%Y%m%d"),
                "page_count": 6,
            },
            timeout=DART_TIMEOUT,
        )

    profile: Dict[str, str] = {}
    disclosures: List[Dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_comp = pool.submit(_fetch_company)
        fut_list = pool.submit(_fetch_list)

        try:
            comp_res = fut_comp.result()
            if comp_res.ok:
                comp_data = comp_res.json()
                if comp_data.get("status") == "000":
                    est_raw = str(comp_data.get("est_dt", "")).strip()
                    est_fmt = f"{est_raw[:4]}-{est_raw[4:6]}-{est_raw[6:]}" if len(est_raw) == 8 else est_raw
                    hm_url = str(comp_data.get("hm_url", "")).strip()
                    if hm_url and not hm_url.startswith(("http://", "https://")):
                        hm_url = f"https://{hm_url}"
                    profile = {
                        "ceo_name": str(comp_data.get("ceo_nm", "")).strip(),
                        "established": est_fmt,
                        "fiscal_month": f"{comp_data.get('acc_mt', '')}월" if comp_data.get("acc_mt") else "",
                        "homepage": hm_url,
                        "address": str(comp_data.get("adres", "")).strip(),
                    }
                elif comp_data.get("status") in ("010", "011", "020"):
                    raise RuntimeError(f"Open DART API 인증/한도 오류: {comp_data.get('message', '')}")
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning(f"[DART] 기업개황 조회 실패 (code={stock_code}): {exc}")

        try:
            list_res = fut_list.result()
            if list_res.ok:
                list_data = list_res.json()
                if list_data.get("status") == "000":
                    for item in (list_data.get("list") or [])[:6]:
                        rcp_no = str(item.get("rcept_no", "")).strip()
                        dt_raw = str(item.get("rcept_dt", "")).strip()
                        dt_fmt = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:]}" if len(dt_raw) == 8 else dt_raw
                        disclosures.append({
                            "title": str(item.get("report_nm", "")).strip(),
                            "date": dt_fmt,
                            "filer": str(item.get("flr_nm", "")).strip(),
                            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcp_no}" if rcp_no else "",
                        })
        except Exception as exc:
            logger.warning(f"[DART] 공시 목록 조회 실패 (code={stock_code}): {exc}")

    logger.info(f"[DART] Open DART 조회 완료 (code={stock_code}, 공시={len(disclosures)}건)")
    return {
        "corp_code": corp_code,
        "profile": profile,
        "disclosures": disclosures,
    }
