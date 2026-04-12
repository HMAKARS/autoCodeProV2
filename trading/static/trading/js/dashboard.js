/* 대시보드 실시간 업데이트 */

function api(url) {
    return fetch(url).then(r => r.json()).catch(() => null);
}

function fmt(n) {
    if (n === undefined || n === null || isNaN(n)) return '-';
    return Number(n).toLocaleString('ko-KR');
}

function fmtCompact(n) {
    if (n === undefined || n === null || isNaN(n)) return '-';
    n = Number(n);
    if (n >= 1e8) return (n / 1e8).toFixed(0) + '억';
    if (n >= 1e4) return (n / 1e4).toFixed(0) + '만';
    return fmt(n);
}

function fmtPct(n) {
    if (n === undefined || n === null || isNaN(n)) return '-';
    const v = Number(n);
    const cls = v > 0 ? 'profit' : v < 0 ? 'loss' : '';
    const sign = v > 0 ? '+' : '';
    return '<span class="' + cls + '">' + sign + v.toFixed(2) + '%</span>';
}

function fmtQty(n) {
    if (n === undefined || n === null) return '-';
    n = Number(n);
    if (n >= 1) return n.toFixed(2);
    if (n >= 0.01) return n.toFixed(4);
    return n.toFixed(6);
}

/* ── 계좌 ── */
function updateAccount() {
    api('/api/fetch_account_data/').then(function(d) {
        if (!d || !d.accounts) return;
        var body = document.getElementById('accountBody');
        if (d.accounts.length === 0) {
            body.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-dim)">보유 자산 없음</td></tr>';
            return;
        }
        body.innerHTML = d.accounts.map(function(a) {
            var qty = a.currency === 'KRW' ? fmt(Math.round(a.balance)) : fmtQty(a.balance);
            var avg = a.avg_buy_price > 0 ? fmt(Math.round(a.avg_buy_price)) : '-';
            var evalAmt = fmt(Math.round(a.eval_amount));
            var pnl = a.currency !== 'KRW' && a.avg_buy_price > 0 ? fmtPct(a.pnl_pct) : '-';
            return '<tr><td>' + a.currency + '</td><td>' + qty + '</td><td>' + avg + '</td><td>' + evalAmt + '</td><td>' + pnl + '</td></tr>';
        }).join('');
    });
}

/* ── 코인 시세 ── */
function updateCoins() {
    api('/api/fetch_coin_data/').then(function(d) {
        if (!d || !d.coins) return;
        var body = document.getElementById('coinBody');
        body.innerHTML = d.coins.slice(0, 15).map(function(c) {
            var rate = c.signed_change_rate * 100;
            var vol = fmtCompact(c.acc_trade_price_24h);
            var name = c.market.replace('KRW-', '');
            return '<tr><td>' + name + '</td><td>' + fmt(c.trade_price) + '</td><td>' + fmtPct(rate) + '</td><td>' + vol + '</td></tr>';
        }).join('');
    });
}

/* ── 시장 상태 ── */
function updateMarket() {
    api('/api/get_market_volume/').then(function(d) {
        if (!d) return;
        var badge = document.getElementById('marketBadge');
        badge.textContent = d.market_state_label;
        badge.className = 'market-badge ' + d.market_state;
    });
}

/* ── 거래 로그 ── */
function updateLogs() {
    api('/api/trade_logs/').then(function(d) {
        if (!d) return;
        var panel = document.getElementById('logPanel');
        if (d.logs.length === 0) {
            panel.innerHTML = '<div style="color:var(--text-dim)">로그 없음</div>';
            return;
        }
        panel.innerHTML = d.logs.map(function(l) { return '<div>' + l + '</div>'; }).join('');
        panel.scrollTop = panel.scrollHeight;
    });
}

/* ── 자동매매 상태 ── */
function updateStatus() {
    api('/api/check_auto_trading/').then(function(d) {
        if (!d) return;
        var el = document.getElementById('tradeStatus');
        if (d.is_running) {
            el.textContent = '실행 중';
            el.className = 'status-badge on';
        } else {
            el.textContent = '중지됨';
            el.className = 'status-badge off';
        }
    });
}

/* ── 최근 매도 ── */
function updateRecent() {
    api('/api/getRecntTradeLog/').then(function(d) {
        if (!d || !d.trades) return;
        var body = document.getElementById('recentBody');
        if (d.trades.length === 0) {
            body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-dim)">내역 없음</td></tr>';
            return;
        }
        body.innerHTML = d.trades.map(function(t) {
            return '<tr><td>' + t.market.replace('KRW-', '') + '</td><td>' + fmt(Math.round(t.buy_price)) + '</td><td>-</td><td>' + t.created_at + '</td></tr>';
        }).join('');
    });
}

/* ── 수익 로그 ── */
function updateProfit() {
    api('/api/recentProfitLog/').then(function(d) {
        if (!d || !d.logs) return;
        var body = document.getElementById('profitBody');
        if (d.logs.length === 0) {
            body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-dim)">내역 없음</td></tr>';
            return;
        }
        body.innerHTML = d.logs.map(function(l) {
            return '<tr><td>' + l.market.replace('KRW-', '') + '</td><td>' + fmt(Math.round(l.buy_price)) + '</td><td>' + fmt(Math.round(l.sell_price)) + '</td><td>' + fmtPct(l.pnl_pct) + '</td></tr>';
        }).join('');
    });
}

/* ── 자동매매 시작/중지 ── */
function startTrade() {
    var budget = document.getElementById('budgetInput').value;
    api('/auto_trade/start/?budget=' + budget);
}

function stopTrade() {
    api('/auto_trade/stop/');
}

/* ── 주기적 갱신 ── */
setInterval(updateLogs, 1000);
setInterval(updateAccount, 1500);
setInterval(updateCoins, 2000);
setInterval(updateMarket, 3000);
setInterval(updateRecent, 3000);
setInterval(updateStatus, 5000);
setInterval(updateProfit, 5000);

/* ── 초기 로드 ── */
updateAccount();
updateCoins();
updateMarket();
updateLogs();
updateStatus();
updateRecent();
updateProfit();
