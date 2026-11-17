import json
import os
import logging
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

from collector import collect_stock_data, validate_stock_code
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
    dify_analysis_key = os.getenv('DIFY_ANALYSIS_API_KEY', '').strip()
    dify_tech_key = os.getenv('DIFY_TECH_API_KEY', '').strip()
    
    # 보안 규칙: 실제 키 값은 반환하지 않고 설정 여부(True/False)만 반환
    return jsonify({
        "status": "ok",
        "keys_configured": {
            "serper": bool(serper_key),
            "gemini": bool(gemini_key),
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


@app.route('/api/chat/analysis', methods=['POST'])
def chat_analysis():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get('code', '')).strip()
    question = str(payload.get('question', '')).strip()
    conversation_id = str(payload.get('conversation_id', '')).strip()

    logger.info(f"[REQUEST] POST /api/chat/analysis code={code}")

    validation_error = validate_stock_code(code)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    if not question:
        return jsonify({"error": "질문 내용을 입력해 주세요."}), 400

    try:
        stock_data = collect_stock_data(code)
    except RuntimeError as exc:
        logger.error(f"[ERROR] 종목 근거 데이터 수집 실패 (code={code}): {exc}", exc_info=True)
        return jsonify({"error": str(exc)}), 400

    context_json = json.dumps(stock_data, ensure_ascii=False, indent=2)
    full_query = (
        f"[수집된 종목 근거 데이터 (JSON)]\n"
        f"{context_json}\n\n"
        f"[사용자 질문]\n"
        f"{question}"
    )

    try:
        dify_res = ask_dify_chatbot(
            bot_type="analysis",
            query=full_query,
            conversation_id=conversation_id,
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
        result = calculate_rebalancing(raw_codes)
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
    code = str(payload.get('code', '')).strip()
    logger.info(f"[REQUEST] POST /api/technical code={code}")

    try:
        result = calculate_technical_indicators(code)
        return jsonify(result), 200
    except (ValueError, RuntimeError) as exc:
        logger.warning(f"[ERROR] 기술지표 계산 실패 (code={code}): {exc}")
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.error(f"[ERROR] 기술지표 서버 오류 (code={code})", exc_info=True)
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
