/* 대시보드 실시간 업데이트 */

function api(url) {
    return fetch(url).then(r => r.json()).catch(() => null);
}

function fmt(n) {
    if (n === undefined || n === null) return '-';
    return Number(n).toLocaleString('ko-KR');
}

function fmtPct(n) {
    if (n === undefined || n === null) return '-';
    const v = Number(n);
    const cls = v > 0 ? 'profit' : v < 0 ? 'loss' : '';
    const sign = v > 0 ? '+' : '';
    return `<span class="${cls}">${sign}${v.toFixed(2)}%</span>`;
}

/* 계좌 정보 */
function updateAccount() {
    api('/api/fetch_account_data/').then(d => {
        if (!d) return;
        const body = document.getElementById('accountBody');
        body.innerHTML = d.accounts.map(a => `<tr>
            <td>${a.currency}</td>
            <td>${a.currency === 'KRW' ? fmt(a.balance) : Number(a.balance).toFixed(4)}</td>
            <td>${a.avg_buy_price > 0 ? fmt(a.avg_buy_price) : '-'}</td>
            <td>${fmt(Math.round(a.eval_amount))}</td>
            <td>${a.currency !== 'KRW' ? fmtPct(a.pnl_pct) : '-'}</td>
        </tr>`).join('');
    });
}

/* 코인 시세 */
function updateCoins() {
    api('/api/fetch_coin_data/').then(d => {
        if (!d) return;
        const body = document.getElementById('coinBody');
        body.innerHTML = d.coins.map(c => {
            const rate = c.signed_change_rate * 100;
            const vol = (c.acc_trade_price_24h / 100000000).toFixed(0);
            return `<tr>
                <td>${c.market.replace('KRW-','')}</td>
                <td>${fmt(c.trade_price)}</td>
                <td>${fmtPct(rate)}</td>
                <td>${vol}억</td>
            </tr>`;
        }).join('');
    });
}

/* 시장 상태 */
function updateMarket() {
    api('/api/get_market_volume/').then(d => {
        if (!d) return;
        const badge = document.getElementById('marketBadge');
        badge.textContent = d.market_state_label;
        badge.className = 'badge ' + d.market_state;
    });
}

/* 거래 로그 */
function updateLogs() {
    api('/api/trade_logs/').then(d => {
        if (!d) return;
        const panel = document.getElementById('logPanel');
        panel.innerHTML = d.logs.map(l => `<div>${l}</div>`).join('');
        panel.scrollTop = panel.scrollHeight;
    });
}

/* 자동매매 상태 */
function updateStatus() {
    api('/api/check_auto_trading/').then(d => {
        if (!d) return;
        const el = document.getElementById('tradeStatus');
        if (d.is_running) {
            el.textContent = '실행 중';
            el.className = 'status on';
        } else {
            el.textContent = '중지됨';
            el.className = 'status off';
        }
    });
}

/* 최근 매도 체결 */
function updateRecent() {
    api('/api/getRecntTradeLog/').then(d => {
        if (!d) return;
        const body = document.getElementById('recentBody');
        body.innerHTML = d.trades.map(t => `<tr>
            <td>${t.market.replace('KRW-','')}</td>
            <td>${fmt(t.buy_price)}</td>
            <td>-</td>
            <td>${t.created_at}</td>
        </tr>`).join('');
    });
}

/* 수익 로그 */
function updateProfit() {
    api('/api/recentProfitLog/').then(d => {
        if (!d) return;
        const body = document.getElementById('profitBody');
        body.innerHTML = d.logs.map(l => `<tr>
            <td>${l.market.replace('KRW-','')}</td>
            <td>${fmt(l.buy_price)}</td>
            <td>${fmt(l.sell_price)}</td>
            <td>${fmtPct(l.pnl_pct)}</td>
            <td>${fmt(Math.round(l.buy_krw))}</td>
        </tr>`).join('');
    });
}

/* 자동매매 시작/중지 */
function startTrade() {
    const budget = document.getElementById('budgetInput').value;
    api(`/auto_trade/start/?budget=${budget}`);
}

function stopTrade() {
    api('/auto_trade/stop/');
}

/* 주기적 갱신 */
setInterval(updateLogs, 1000);
setInterval(updateAccount, 1000);
setInterval(updateCoins, 2000);
setInterval(updateMarket, 3000);
setInterval(updateRecent, 3000);
setInterval(updateStatus, 5000);
setInterval(updateProfit, 5000);

/* 초기 로드 */
updateAccount();
updateCoins();
updateMarket();
updateLogs();
updateStatus();
updateRecent();
updateProfit();
