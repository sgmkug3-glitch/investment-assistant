import json
import os
import logging
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from collector import collect_stock_data, resolve_stock_code, search_stocks, validate_stock_code
from dify_client import ask_dify_chatbot
from portfolio import calculate_rebalancing
from technical import calculate_technical_indicators

# .env 환경변수 로드
load_dotenv()

# 로깅 설정 (print 대신 logging 사용)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.route('/', methods=['GET'])
def index():
    logger.info("[REQUEST] GET /")
    return render_template('index.html')

@app.route('/test', methods=['GET'])
def test_page():
    logger.info("[REQUEST] GET /test")
    return render_template('test.html')

@app.route('/health', methods=['GET'])
def health():
    logger.info("[REQUEST] GET /health")
    serper_key = os.getenv('SERPER_API_KEY', '').strip()
    gemini_key = os.getenv('GEMINI_API_KEY', '').strip()
    dart_key = os.getenv('DART_API_KEY', '').strip()
    dify_analysis_key = os.getenv('DIFY_ANALYSIS_API_KEY', '').strip()
    dify_tech_key = os.getenv('DIFY_TECH_API_KEY', '').strip()
    
    # 보안 규칙: 실제 키 값은 반환하지 않고 설정 여부(True/False)만 반환
    return jsonify({
        "status": "ok",
        "keys_configured": {
            "serper": bool(serper_key),
            "gemini": bool(gemini_key),
            "dart": bool(dart_key),
            "dify_analysis": bool(dify_analysis_key),
            "dify_tech": bool(dify_tech_key),
        }
    }), 200

@app.route('/fetch', methods=['POST'])
def fetch():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get('code', '')).strip()
    logger.info(f"[REQUEST] POST /fetch code={code}")

    validation_error = validate_stock_code(code)
    if validation_error:
        logger.warning(f"[ERROR] 유효하지 않은 종목코드 요청 (code={code}): {validation_error}")
        return jsonify({"error": validation_error}), 400

    try:
        result = collect_stock_data(code)
        logger.info(
            f"[RESPONSE] 수집 성공 / name={result.get('name')}, "
            f"financials={len(result.get('financials', []))}, "
            f"news={len(result.get('news', []))}, "
            f"errors={len(result.get('errors', []))}"
        )
        return jsonify(result), 200
    except RuntimeError as exc:
        logger.error(f"[ERROR] 종목 수집 실패 (code={code}): {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.error(f"[ERROR] 예기치 못한 서버 오류 (code={code})", exc_info=True)
        return jsonify({"error": "서버 내부 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}), 500


EXPERT_ANALYSIS_GUIDE = """당신은 사용자 개인(1인 전용)의 투자 의사결정을 돕는 냉철하면서도 설명이 쉬운 전속 퀀트·애널리스트입니다.
아래 [정량 스코어카드]와 [수집된 종목 근거 데이터 (JSON)]에 포함된 수치·수급·컨센서스·리포트·뉴스 사실만을 근거로, 주식 초보자도 한눈에 이해할 수 있는 전문 마크다운 리포트를 작성하세요.

[절대 준수 지침]
1. "법규상 팔아라/사라 말할 수 없다", "본인의 판단에 맡긴다" 같은 원론적 회피나 장황한 설교를 절대 쓰지 마세요.
2. 반드시 리포트 맨 첫 줄에 데이터에 기반한 명확한 한쪽 방향 결론을 먼저 제시하세요.
   예) **결론: [보유/분할매수 우위]** 또는 **결론: [반등 시 비중 축소 우위]** 또는 **결론: [손절/교체 검토 우위]**
3. **초보자 친화적 쉬운 풀이**: PER, PBR, ROE, 컨센서스, 순매수 같은 용어를 쓸 때는 반드시 괄호 안에 쉬운 뜻풀이나 직관적 비유를 함께 적으세요.
   예) "PER 4.9배(현재 버는 돈 속도로 약 4.9년이면 회사 몸값을 번다는 뜻의 저평가 구간)"
4. 근거 데이터에 없는 수치는 절대 지어내지 말고, 추정치(is_consensus: true)는 반드시 '추정치(E)'로 명시하세요.
5. 각 항목은 군더더기 없이 핵심 수치와 판단 이유만 2~4줄로 명확하게 정리하세요.

[분석 필수 목차]
### 결론 및 핵심 전략 (단도직입 요약)
### 1. 현재 주가 위치 & 증권사 목표주가 (컨센서스)
(현재가, 52주 최고/최저 위치, 증권사 평균 목표주가 및 상승여력, 투자의견 점수)
### 2. 밸류에이션 & 실적·분기 흐름 (초보자 쉬운 풀이 포함)
(PER vs 추정PER, PBR·BPS, 연간/최근 4분기 매출·영업이익·ROE 추이 — ETF인 경우 보수/NAV/수익률 중심으로 설명)
### 3. 최근 5일 큰손(외국인·기관) 수급 & 재무 안전성
(외국인·기관 최근 5일 순매수/순매도 흐름, 부채비율·유보율, 동종 업종 경쟁사 비교)
### 4. 증권사 리포트 · DART 공식 공시 · 최신 뉴스 & 체크포인트
(DART 공식 공시(dart.disclosures), 증권사 리포트, 뉴스 요약 및 향후 지켜볼 구체적 기준 2가지)"""


def _build_quant_scorecard(stock_data: dict) -> dict:
    """수집된 종목 데이터에서 AI가 직접적 판단을 내릴 수 있도록 객관적 정량 시그널을 계산한다."""
    snap = stock_data.get("snapshot") or {}
    cons_info = stock_data.get("consensus") or {}
    trend = stock_data.get("investor_trend") or []
    fins = [f for f in (stock_data.get("financials") or []) if not f.get("is_consensus")]
    cons = [f for f in (stock_data.get("financials") or []) if f.get("is_consensus")]

    price = snap.get("current_price")
    high_52 = snap.get("high_52w")
    low_52 = snap.get("low_52w")
    per = snap.get("per")
    cns_per = snap.get("cns_per")

    drop_from_high_pct = None
    band_pos_pct = None
    if price and high_52 and low_52 and high_52 > low_52:
        drop_from_high_pct = round((price - high_52) / high_52 * 100, 1)
        band_pos_pct = round((price - low_52) / (high_52 - low_52) * 100, 1)

    foreign_5d_net = sum((d.get("foreigner_net") or 0) for d in trend) if trend else None
    organ_5d_net = sum((d.get("organ_net") or 0) for d in trend) if trend else None

    latest_fin = fins[-1] if fins else {}
    latest_cons = cons[-1] if cons else {}

    score = 0
    reasons = []
    if per and cns_per and cns_per < per:
        score += 1
        reasons.append(f"실적 개선으로 추정PER({cns_per}배)이 현재PER({per}배)보다 낮아짐")
    if latest_fin.get("roe") and latest_fin["roe"] >= 15:
        score += 1
        reasons.append(f"최근 확정 ROE {latest_fin['roe']}%로 자본효율 우수")
    if latest_fin.get("debt_ratio") is not None and latest_fin["debt_ratio"] < 100:
        score += 1
        reasons.append(f"부채비율 {latest_fin['debt_ratio']}%로 재무 건전")
    if latest_cons.get("operating_income") and latest_fin.get("operating_income"):
        if latest_cons["operating_income"] > latest_fin["operating_income"]:
            score += 1
            reasons.append("차기 영업이익 추정치(E) 추가 성장 전망")
    if cons_info.get("upside_pct") and cons_info["upside_pct"] >= 15:
        reasons.append(f"증권사 평균 목표주가 대비 상승여력 +{cons_info['upside_pct']}%")

    if stock_data.get("stock_type") == "etf":
        stance = "ETF 상품 (기초지수 추종 · 총보수/괴리율/분배율 및 1년 수익률 기준 판단)"
    elif score >= 3:
        stance = "펀더멘털 우위 (보유 및 추세 회복 대기 유리)"
    elif score == 2:
        stance = "중립 (분할 대응 및 실적 확인 필요)"
    else:
        stance = "보수적 접근 필요 (반등 시 비중 축소·리스크 관리 유리)"

    return {
        "stock_type": stock_data.get("stock_type", "stock"),
        "quant_score": f"{score}/4" if stock_data.get("stock_type") != "etf" else "N/A (ETF)",
        "calculated_stance": stance,
        "drop_from_52w_high_pct": drop_from_high_pct,
        "position_in_52w_band_pct": band_pos_pct,
        "consensus_upside_pct": cons_info.get("upside_pct"),
        "foreign_5d_net_shares": foreign_5d_net,
        "organ_5d_net_shares": organ_5d_net,
        "key_signals": reasons,
    }


@app.route('/api/chat/analysis', methods=['POST'])
def chat_analysis():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get('code', '')).strip()
    question = str(payload.get('question', '')).strip()
    conversation_id = str(payload.get('conversation_id', '')).strip()
    mode = str(payload.get('mode', 'init')).strip()

    logger.info(f"[REQUEST] POST /api/chat/analysis code={code}, mode={mode}")

    validation_error = validate_stock_code(code)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    # 후속 채팅(mode=='chat'이고 conversation_id 존재)은 중복 수집 없이 대화 맥락 이어가기
    if mode == 'chat' and conversation_id:
        if not question:
            return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

        direct_query = (
            f"{question}\n\n"
            f"[응답 지침: '매수/매도를 권유할 수 없다'는 회피나 장황한 설교 없이, "
            f"앞서 제공된 수치와 근거를 바탕으로 데이터상 가장 유리한 한쪽 방향을 단도직입적이고 짧게 답변하세요.]"
        )
        try:
            dify_res = ask_dify_chatbot(
                bot_type="analysis",
                query=direct_query,
                conversation_id=conversation_id,
            )
            return jsonify({
                "answer": dify_res["answer"],
                "conversation_id": dify_res["conversation_id"],
            }), 200
        except RuntimeError as exc:
            logger.error(f"[ERROR] 탭1 후속 채팅 Dify 호출 실패 (code={code}): {exc}")
            return jsonify({"error": str(exc)}), 502

    # 초기 조회(mode=='init' 또는 새 대화): 종목 데이터 수집 + 정량 스코어카드 + 전문가 프롬프트
    try:
        stock_data = collect_stock_data(code)
    except RuntimeError as exc:
        logger.error(f"[ERROR] 종목 근거 데이터 수집 실패 (code={code}): {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 400

    scorecard = _build_quant_scorecard(stock_data)
    scorecard_json = json.dumps(scorecard, ensure_ascii=False, indent=2)
    context_json = json.dumps(stock_data, ensure_ascii=False, indent=2)
    user_request = question if question else f"{stock_data['name']}({code}) 종목에 대한 직접적인 전략 결론과 핵심 분석을 작성해 주세요."
    full_query = (
        f"{EXPERT_ANALYSIS_GUIDE}\n\n"
        f"[정량 스코어카드]\n"
        f"{scorecard_json}\n\n"
        f"[수집된 종목 근거 데이터 (JSON)]\n"
        f"{context_json}\n\n"
        f"[요청 사항]\n"
        f"{user_request}"
    )

    try:
        dify_res = ask_dify_chatbot(
            bot_type="analysis",
            query=full_query,
            conversation_id="",
        )
        return jsonify({
            "answer": dify_res["answer"],
            "conversation_id": dify_res["conversation_id"],
            "stock_data": stock_data,
        }), 200
    except RuntimeError as exc:
        logger.error(f"[ERROR] 탭1 Dify 호출 실패 (code={code}): {exc}")
        return jsonify({
            "error": str(exc),
            "stock_data": stock_data,
        }), 502


@app.route('/api/search', methods=['GET'])
def search_stock():
    query = str(request.args.get('q', '')).strip()
    if not query:
        return jsonify({"items": []}), 200
    items = search_stocks(query, limit=6)
    return jsonify({"items": items}), 200


@app.route('/api/rebalance', methods=['POST'])
def rebalance():
    payload = request.get_json(silent=True) or {}
    raw_codes = payload.get('codes', [])
    if isinstance(raw_codes, str):
        raw_codes = [c.strip() for c in raw_codes.split(',') if c.strip()]
    elif not isinstance(raw_codes, list):
        raw_codes = []

    logger.info(f"[REQUEST] POST /api/rebalance codes={raw_codes}")

    try:
        resolved_codes = [resolve_stock_code(c) for c in raw_codes]
        result = calculate_rebalancing(resolved_codes)
        return jsonify(result), 200
    except (ValueError, RuntimeError) as exc:
        logger.warning(f"[ERROR] 리밸런싱 계산 실패 (codes={raw_codes}): {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.error(f"[ERROR] 리밸런싱 서버 오류 (codes={raw_codes})", exc_info=True)
        return jsonify({"error": "리밸런싱 시뮬레이션 중 서버 오류가 발생했습니다."}), 500


@app.route('/api/technical', methods=['POST'])
def technical():
    payload = request.get_json(silent=True) or {}
    raw_code = str(payload.get('code', '')).strip()
    logger.info(f"[REQUEST] POST /api/technical code={raw_code}")

    try:
        code = resolve_stock_code(raw_code)
        result = calculate_technical_indicators(code)
        return jsonify(result), 200
    except (ValueError, RuntimeError) as exc:
        logger.warning(f"[ERROR] 기술지표 계산 실패 (code={raw_code}): {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.error(f"[ERROR] 기술지표 서버 오류 (code={raw_code})", exc_info=True)
        return jsonify({"error": "기술지표 계산 중 서버 오류가 발생했습니다."}), 500


@app.route('/api/chat/technical', methods=['POST'])
def chat_technical():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get('code', '')).strip()
    question = str(payload.get('question', '')).strip()
    indicators = payload.get('indicators')
    conversation_id = str(payload.get('conversation_id', '')).strip()

    logger.info(f"[REQUEST] POST /api/chat/technical code={code}")

    if not code:
        return jsonify({"error": "먼저 종목코드를 입력하여 차트와 지표를 조회해 주세요."}), 400
    if not question:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    # 프론트에서 전달받은 계산 숫자가 없으면 백엔드에서 직접 계산하여 주입
    if not isinstance(indicators, dict) or not indicators:
        try:
            indicators = calculate_technical_indicators(code).get("latest", {})
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

    indicators_json = json.dumps(indicators, ensure_ascii=False, indent=2)
    full_query = (
        f"[계산된 최신 기술지표 숫자 (종목코드: {code})]\n"
        f"{indicators_json}\n\n"
        f"[사용자 질문]\n"
        f"{question}"
    )

    try:
        dify_res = ask_dify_chatbot(
            bot_type="tech",
            query=full_query,
            conversation_id=conversation_id,
        )
        return jsonify({
            "answer": dify_res["answer"],
            "conversation_id": dify_res["conversation_id"],
        }), 200
    except RuntimeError as exc:
        logger.error(f"[ERROR] 탭3 Dify 호출 실패 (code={code}): {exc}")
        return jsonify({"error": str(exc)}), 502


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    logger.info(f"[START] Starting Flask server on http://127.0.0.1:5000 (debug={debug_mode})")
    app.run(host='127.0.0.1', port=5000, debug=debug_mode)
