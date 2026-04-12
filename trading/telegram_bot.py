"""텔레그램 봇 알림 모듈.

매수/매도/에러 등 주요 이벤트 발생 시 텔레그램으로 알림을 전송한다.
"""

import logging
import threading

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}"


def _get_url(method: str) -> str:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    return f"{_BASE_URL.format(token=token)}/{method}"


def _is_configured() -> bool:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    return bool(token and chat_id)


def send_message(text: str):
    """텔레그램 메시지 전송 (비동기, 실패해도 매매에 영향 없음)."""
    if not _is_configured():
        return
    threading.Thread(target=_send, args=(text,), daemon=True).start()


def _send(text: str):
    """실제 메시지 전송."""
    try:
        chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
        resp = requests.post(
            _get_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            logger.warning("텔레그램 전송 실패: %s", resp.text)
    except Exception as e:
        logger.warning("텔레그램 전송 에러: %s", e)


def get_chat_id() -> str | None:
    """봇에게 온 최근 메시지에서 chat_id를 추출한다."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None
    try:
        resp = requests.get(
            f"{_BASE_URL.format(token=token)}/getUpdates",
            timeout=10,
        )
        data = resp.json()
        if data.get("ok") and data.get("result"):
            return str(data["result"][-1]["message"]["chat"]["id"])
    except Exception as e:
        logger.warning("chat_id 조회 실패: %s", e)
    return None
