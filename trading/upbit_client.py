"""업비트 API 클라이언트 (JWT 인증)."""

import hashlib
import logging
import time
import uuid as uuid_mod
from urllib.parse import urlencode, unquote

import jwt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.upbit.com"


def _get_token(query_params: dict | None = None) -> str:
    """JWT 토큰 생성."""
    payload = {
        "access_key": settings.UPBIT_API_KEY,
        "nonce": str(uuid_mod.uuid4()),
    }
    if query_params:
        query_string = unquote(urlencode(query_params, doseq=True))
        query_hash = hashlib.sha512(query_string.encode()).hexdigest()
        payload["query_hash"] = query_hash
        payload["query_hash_alg"] = "SHA512"

    return jwt.encode(payload, settings.UPBIT_SECRET_KEY, algorithm="HS256")


def _headers(query_params: dict | None = None) -> dict:
    token = _get_token(query_params)
    return {"Authorization": f"Bearer {token}"}


# ── 계좌 ────────────────────────────────────────────────

def get_accounts() -> list[dict]:
    """보유 자산 전체 조회."""
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/accounts", headers=_headers(), timeout=5
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("계좌 조회 실패: %s", e)
        return []


def get_krw_balance() -> float:
    """KRW 잔고 조회."""
    accounts = get_accounts()
    for a in accounts:
        if a.get("currency") == "KRW":
            return float(a.get("balance", 0))
    return 0.0


# ── 시장 데이터 ─────────────────────────────────────────

def get_krw_markets() -> list[str]:
    """KRW 마켓 목록 조회."""
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/market/all", params={"isDetails": "false"}, timeout=5
        )
        resp.raise_for_status()
        return [
            m["market"] for m in resp.json()
            if m["market"].startswith("KRW-")
        ]
    except Exception as e:
        logger.error("마켓 목록 조회 실패: %s", e)
        return []


def get_ticker(markets: list[str]) -> list[dict]:
    """여러 코인 시세 한 번에 조회."""
    if not markets:
        return []
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/ticker",
            params={"markets": ",".join(markets)},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("시세 조회 실패: %s", e)
        return []


def get_orderbook(markets: list[str]) -> list[dict]:
    """호가 정보 조회 (배치)."""
    if not markets:
        return []
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/orderbook",
            params={"markets": ",".join(markets)},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("호가 조회 실패: %s", e)
        return []


def get_candles_seconds(market: str, count: int = 60) -> list[dict]:
    """초봉 캔들 데이터 조회."""
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/candles/seconds",
            params={"market": market, "count": count},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("%s 캔들 조회 실패: %s", market, e)
        return []


# ── 주문 ────────────────────────────────────────────────

def buy_market_order(market: str, price: float) -> dict | None:
    """시장가 매수. price = 총 매수 금액(KRW)."""
    params = {
        "market": market,
        "side": "bid",
        "ord_type": "price",
        "price": str(price),
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/v1/orders",
            json=params,
            headers=_headers(params),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("매수 주문 실패 %s: %s", market, e)
        return None


def sell_market_order(market: str, volume: float) -> dict | None:
    """시장가 매도. volume = 매도 수량."""
    params = {
        "market": market,
        "side": "ask",
        "ord_type": "market",
        "volume": str(volume),
    }
    try:
        resp = requests.post(
            f"{BASE_URL}/v1/orders",
            json=params,
            headers=_headers(params),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("매도 주문 실패 %s: %s", market, e)
        return None


def get_order(uuid: str) -> dict | None:
    """주문 상태 조회 (UUID 기반)."""
    params = {"uuid": uuid}
    try:
        resp = requests.get(
            f"{BASE_URL}/v1/order",
            params=params,
            headers=_headers(params),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("주문 조회 실패 %s: %s", uuid, e)
        return None


def check_order_done(uuid: str) -> bool:
    """주문 체결 완료 여부 확인."""
    order = get_order(uuid)
    if order and order.get("state") == "done":
        return True
    return False
