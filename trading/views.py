"""웹 API 뷰."""

import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta

from . import upbit_client
from .models import TradeRecord, AskRecord
from .market_analyzer import get_market_state
from .auto_trader import get_trader

logger = logging.getLogger(__name__)


def dashboard(request):
    """메인 대시보드 페이지."""
    return render(request, "trading/dashboard.html")


def start_auto_trade(request):
    """자동매매 시작."""
    budget = float(request.GET.get("budget", 50000))
    trader = get_trader()
    if trader.is_running:
        return JsonResponse({"status": "already_running"})
    trader.start(budget)
    return JsonResponse({"status": "started", "budget": budget})


def stop_auto_trade(request):
    """자동매매 중지."""
    trader = get_trader()
    trader.stop()
    return JsonResponse({"status": "stopped"})


def check_auto_trading(request):
    """자동매매 실행 여부."""
    trader = get_trader()
    return JsonResponse({"is_running": trader.is_running})


def fetch_account_data(request):
    """계좌 정보 조회."""
    accounts = upbit_client.get_accounts()
    # 현재가 매핑
    holdings = []
    coin_markets = []
    for a in accounts:
        cur = a.get("currency", "")
        bal = float(a.get("balance", 0))
        locked = float(a.get("locked", 0))
        avg = float(a.get("avg_buy_price", 0))
        if cur == "KRW":
            holdings.append({
                "currency": cur,
                "balance": bal,
                "locked": locked,
                "avg_buy_price": 0,
                "current_price": 0,
                "eval_amount": bal,
                "pnl_pct": 0,
            })
        elif bal > 0:
            coin_markets.append(f"KRW-{cur}")
            holdings.append({
                "currency": cur,
                "balance": bal,
                "locked": locked,
                "avg_buy_price": avg,
                "current_price": 0,
                "eval_amount": 0,
                "pnl_pct": 0,
            })

    # 유효 마켓만 필터 (상장폐지 코인 제외)
    valid_markets = set(upbit_client.get_krw_markets())
    coin_markets = [m for m in coin_markets if m in valid_markets]

    # 현재가 일괄 조회
    if coin_markets:
        tickers = upbit_client.get_ticker(coin_markets)
        price_map = {t["market"]: float(t["trade_price"]) for t in tickers}
        for h in holdings:
            if h["currency"] != "KRW":
                market = f"KRW-{h['currency']}"
                price = price_map.get(market, 0)
                h["current_price"] = price
                h["eval_amount"] = h["balance"] * price
                if h["avg_buy_price"] > 0:
                    h["pnl_pct"] = (
                        (price - h["avg_buy_price"]) / h["avg_buy_price"]
                    ) * 100

    return JsonResponse({"accounts": holdings})


def fetch_coin_data(request):
    """상위 코인 시세 조회 (거래대금 순)."""
    markets = upbit_client.get_krw_markets()
    tickers = upbit_client.get_ticker(markets)
    tickers.sort(
        key=lambda t: float(t.get("acc_trade_price_24h", 0)), reverse=True
    )
    coins = []
    for t in tickers[:20]:
        coins.append({
            "market": t.get("market"),
            "trade_price": float(t.get("trade_price", 0)),
            "signed_change_rate": float(t.get("signed_change_rate", 0)),
            "acc_trade_price_24h": float(t.get("acc_trade_price_24h", 0)),
        })
    return JsonResponse({"coins": coins})


def trade_logs(request):
    """거래 로그 조회 (최근 50건)."""
    trader = get_trader()
    return JsonResponse({"logs": trader.trade_logs})


def get_market_volume(request):
    """현재 시장 상태 조회."""
    state = get_market_state()
    labels = {"bullish": "상승장", "bearish": "하락장", "neutral": "보합장"}
    return JsonResponse({
        "market_state": state,
        "market_state_label": labels.get(state, "보합장"),
    })


def get_recent_trade_log(request):
    """최근 매도 체결 내역."""
    records = TradeRecord.objects.filter(is_active=False).order_by("-created_at")[:10]
    trades = []
    for r in records:
        trades.append({
            "market": r.market,
            "buy_price": r.buy_price,
            "highest_price": r.highest_price,
            "buy_krw_price": r.buy_krw_price,
            "created_at": r.created_at.strftime("%m-%d %H:%M:%S"),
        })
    return JsonResponse({"trades": trades})


def recent_profit_log(request):
    """최근 수익 로그."""
    records = TradeRecord.objects.filter(is_active=False).order_by("-created_at")[:20]
    logs = []
    for r in records:
        # 현재가 or 최고가 기반 추정 수익률
        if r.highest_price > 0 and r.buy_price > 0:
            fee = 0.0005
            real_buy = r.buy_price * (1 + fee)
            real_sell = r.highest_price * (1 - fee)
            pnl_pct = ((real_sell - real_buy) / real_buy) * 100
        else:
            pnl_pct = 0
        logs.append({
            "market": r.market,
            "buy_price": r.buy_price,
            "sell_price": r.highest_price,
            "pnl_pct": round(pnl_pct, 2),
            "buy_krw": r.buy_krw_price,
            "date": r.created_at.strftime("%m-%d %H:%M"),
        })
    return JsonResponse({"logs": logs})
