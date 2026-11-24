import logging
import os
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

DIFY_TIMEOUT = 45

BOT_ENV_KEY_MAP = {
    "analysis": "DIFY_ANALYSIS_API_KEY",
    "tech": "DIFY_TECH_API_KEY",
}


def ask_dify_chatbot(
    bot_type: str,
    query: str,
    inputs: Optional[Dict[str, Any]] = None,
    conversation_id: str = "",
    user_id: str = "investment-assistant-user",
) -> Dict[str, str]:
    """Dify 챗봇 백엔드 서비스 API(/chat-messages)를 blocking 모드로 호출한다."""
    env_key_name = BOT_ENV_KEY_MAP.get(bot_type)
    if not env_key_name:
        raise ValueError(f"지원하지 않는 Dify 챗봇 유형입니다: {bot_type}")

    api_key = os.getenv(env_key_name, "").strip()
    if not api_key:
        logger.error(f"[ERROR] Dify API Key 미설정 (bot={bot_type}, env={env_key_name})")
        raise RuntimeError(
            f"Dify 챗봇 API Key({env_key_name})가 설정되지 않았습니다. (.env 파일을 확인해 주세요)"
        )

    base_url = os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1").strip().rstrip("/")
    url = f"{base_url}/chat-messages"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": inputs or {},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": conversation_id or "",
        "user": user_id,
    }

    logger.info(f"[DIFY] Dify 챗봇 API 호출 시작 (bot={bot_type})")

    max_attempts = 2
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=DIFY_TIMEOUT)
        except requests.Timeout as exc:
            logger.error(f"[ERROR] Dify API 네트워크 타임아웃 (bot={bot_type})", exc_info=True)
            raise RuntimeError("AI 챗봇 응답 대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from exc
        except requests.RequestException as exc:
            logger.error(f"[ERROR] Dify API 연결 실패 (bot={bot_type})", exc_info=True)
            raise RuntimeError("Dify API 서버에 연결할 수 없습니다.") from exc

        if response.status_code in (401, 403):
            logger.error(f"[ERROR] Dify API 인증 실패 (bot={bot_type}, status={response.status_code})")
            raise RuntimeError(f"Dify API 인증에 실패했습니다. ({env_key_name}를 확인해 주세요)")

        if response.ok:
            break

        detail = ""
        try:
            err_json = response.json()
            detail = err_json.get("message", "")
        except ValueError:
            detail = response.text[:150]

        is_transient = (
            response.status_code in (429, 502, 503, 504)
            or any(kw in detail.lower() for kw in ("high demand", "temporary", "overloaded", "rate limit", "unavailable"))
        )
        if is_transient and attempt < max_attempts:
            logger.warning(f"[DIFY] 일시적 AI 서버 혼잡 감지, 1.5초 후 재시도 (attempt={attempt}, bot={bot_type})")
            time.sleep(1.5)
            continue

        logger.error(
            f"[ERROR] Dify API 호출 실패 (bot={bot_type}, status={response.status_code}, detail={detail})"
        )
        if is_transient:
            raise RuntimeError(
                "현재 Dify에 연결된 AI 모델 서버에 일시적으로 요청이 몰려 응답이 지연되고 있습니다. 5~10초 후 다시 시도해 주세요."
            )
        msg = f"Dify 챗봇 호출에 실패했습니다. (HTTP {response.status_code})"
        if detail:
            msg += f" - {detail}"
        raise RuntimeError(msg)

    try:
        data = response.json()
    except ValueError as exc:
        logger.error(f"[ERROR] Dify API JSON 변환 실패 (bot={bot_type})", exc_info=True)
        raise RuntimeError("Dify 응답 데이터를 JSON으로 변환하는 데 실패했습니다.") from exc

    answer = data.get("answer")
    if answer is None:
        logger.error(f"[ERROR] Dify 응답에 answer 필드가 없음 (bot={bot_type})")
        raise RuntimeError("Dify 챗봇으로부터 유효한 답변을 받지 못했습니다.")

    new_conversation_id = str(data.get("conversation_id", ""))
    logger.info(
        f"[DIFY] Dify 챗봇 API 호출 완료 (bot={bot_type}, status=200, conversation_id={new_conversation_id})"
    )

    return {
        "answer": str(answer),
        "conversation_id": new_conversation_id,
    }
