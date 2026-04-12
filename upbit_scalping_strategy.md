# 업비트 볼린저밴드 단타 자동매매 봇 전략서

## 1. 전체 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                    Main Loop (5초 간격)               │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ① 코인 선정 모듈    거래량 상위 N개 자동 선정          │
│         ↓                                           │
│  ② 데이터 수집       업비트 캔들 API → 지표 계산        │
│         ↓                                           │
│  ③ 시그널 엔진       BB + RSI + MACD + Volume 복합판단 │
│         ↓                                           │
│  ④ 리스크 관리       포지션 사이징, 손절/익절 로직       │
│         ↓                                           │
│  ⑤ 주문 실행         시장가 매수/매도                   │
│         ↓                                           │
│  ⑥ 로깅/모니터링     거래 기록, 수익률 추적             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 2. 코인 선정 모듈

### 기준
- **대상 마켓**: KRW 마켓만 (원화 거래)
- **거래량 기준**: 24시간 거래대금 상위 5~10개
- **제외 조건**:
  - 상장 7일 미만 (신규 상장 변동성 회피)
  - 24시간 변동률 ±30% 초과 (펌핑/덤핑 회피)
  - 호가 스프레드 0.5% 이상 (유동성 부족 회피)

### 갱신 주기
- 30분마다 거래량 순위 재계산
- 현재 보유 중인 코인은 매도 완료 전까지 리스트에서 제거하지 않음

### 구현 API
```
GET /v1/market/all          → KRW 마켓 목록
GET /v1/ticker?markets=...  → 24시간 거래대금, 변동률 조회
GET /v1/orderbook?markets=... → 호가 스프레드 확인
```

---

## 3. 기술적 지표 설정

### 3-1. 볼린저밴드 (Bollinger Bands) — 핵심 지표

| 파라미터 | 값 | 설명 |
|---------|-----|------|
| 기간 (period) | 20 | 20봉 이동평균 |
| 표준편차 배수 | 2.0 | 상/하단 밴드 |
| 캔들 단위 | **5분봉** | 단타에 적합한 타임프레임 |

**계산 지표**:
- `%b` = (현재가 - 하단밴드) / (상단밴드 - 하단밴드)
  - 0 이하: 하단 이탈 → 과매도 구간
  - 1 이상: 상단 이탈 → 과매수 구간
- `밴드폭(BW)` = (상단 - 하단) / 중심선
  - 밴드 수축(squeeze) 감지용

### 3-2. RSI (Relative Strength Index) — 과매수/과매도 필터

| 파라미터 | 값 |
|---------|-----|
| 기간 | 14 |
| 과매도 기준 | 30 이하 |
| 과매수 기준 | 70 이상 |

### 3-3. MACD — 추세 방향 확인

| 파라미터 | 값 |
|---------|-----|
| 단기 EMA | 12 |
| 장기 EMA | 26 |
| 시그널 | 9 |

**활용**: MACD 히스토그램의 방향(증가/감소)으로 모멘텀 판단

### 3-4. 거래량 (Volume) — 신뢰도 필터

| 파라미터 | 값 |
|---------|-----|
| 비교 기간 | 20봉 평균 |
| 유효 배수 | 1.5배 이상 |

**활용**: 시그널 발생 시점의 거래량이 평균 대비 1.5배 이상이면 신뢰도 UP

---

## 4. 매매 시그널 전략

### 4-1. 매수 시그널 (BUY)

모든 조건을 **AND**로 결합 (동시 충족 필수):

```
매수 조건:
  ✅ BB %b ≤ 0.0       → 가격이 하단밴드 이하 (과매도)
  ✅ RSI ≤ 30           → RSI도 과매도 확인
  ✅ MACD 히스토그램 > 이전봉  → 하락 모멘텀 둔화 (반등 시작 징후)
  ✅ 거래량 ≥ 20봉 평균 × 1.5  → 거래량 동반 (선택적 가중)
```

**거래량 조건은 가중 방식으로 처리**:
- 거래량 충족 시: 투자금 100% 사용
- 거래량 미충족 시: 투자금 50%만 사용 (반신반의 진입)

### 4-2. 매도 시그널 (SELL)

아래 중 **하나라도** 충족 시 매도 (OR 조건):

```
익절 조건:
  🎯 BB 중심선(20MA) 도달         → 기본 익절 (보수적)
  🎯 BB %b ≥ 1.0                  → 상단밴드 도달 (공격적 익절)
  🎯 RSI ≥ 70                     → 과매수 진입

손절 조건:
  🛑 매수가 대비 -2% 도달          → 고정 손절선
  🛑 BB 하단밴드가 추가 하락 돌파   → 밴드 워킹 다운 (추세적 하락)

시간 손절:
  ⏰ 매수 후 30분(6봉) 경과 시     → 횡보 탈출 (기회비용 관리)
     손익 무관하게 청산
```

### 4-3. 시그널 강도 스코어링 (선택적 고도화)

```python
score = 0

# 볼린저밴드 (가중치 40%)
if percent_b <= -0.1:   score += 40   # 강한 이탈
elif percent_b <= 0.0:  score += 30   # 밴드 터치

# RSI (가중치 30%)
if rsi <= 20:           score += 30   # 극단적 과매도
elif rsi <= 30:         score += 20   # 과매도

# MACD (가중치 20%)
if macd_hist > prev_hist and macd_hist < 0:
    score += 20   # 음→양 전환 직전 (가장 좋은 타이밍)
elif macd_hist > prev_hist:
    score += 10   # 히스토그램 증가 중

# 거래량 (가중치 10%)
if volume >= avg_volume * 2.0:  score += 10
elif volume >= avg_volume * 1.5: score += 5

# 매수 실행 기준
# score >= 70: 풀 사이즈 진입
# score >= 50: 하프 사이즈 진입
# score < 50:  진입 안 함
```

---

## 5. 리스크 관리

### 5-1. 포지션 관리

| 항목 | 설정값 | 설명 |
|------|--------|------|
| 1회 매매금 | 50~100만원 | 설정 파일에서 조정 |
| 최대 동시 보유 | 3개 코인 | 분산 투자 |
| 총 투자한도 | 전체 KRW 잔고의 80% | 여유자금 확보 |
| 일일 최대 거래 | 20회 | 과매매 방지 |
| 일일 최대 손실 | -5만원 | 도달 시 당일 매매 중단 |

### 5-2. 쿨다운 규칙

```
- 같은 코인 손절 후: 15분간 해당 코인 매수 금지
- 연속 3회 손절 시: 전체 매매 30분 중단
- 일일 손실한도 도달: 당일 매매 전면 중단 → 다음날 자동 재개
```

### 5-3. 슬리피지 대응

- **시장가 주문** 사용 (단타는 체결 속도 우선)
- 호가 스프레드 0.3% 이상이면 매매 보류
- 주문 후 미체결 3초 초과 시 취소 후 재시도

---

## 6. 프로젝트 구조 (권장)

```
upbit-scalping-bot/
├── config/
│   └── settings.py          # API키, 매매금, 손절률 등 설정
├── core/
│   ├── market_selector.py   # 거래량 상위 코인 선정
│   ├── data_collector.py    # 캔들 데이터 수집 + 지표 계산
│   ├── signal_engine.py     # 매수/매도 시그널 판단
│   ├── order_executor.py    # 주문 실행 (매수/매도)
│   └── risk_manager.py      # 포지션 관리, 손절/익절, 쿨다운
├── indicators/
│   ├── bollinger.py         # 볼린저밴드 계산
│   ├── rsi.py               # RSI 계산
│   ├── macd.py              # MACD 계산
│   └── volume.py            # 거래량 분석
├── utils/
│   ├── upbit_client.py      # 업비트 API 래퍼 (pyupbit 활용)
│   └── logger.py            # 거래 로그 기록
├── logs/
│   └── trades.csv           # 거래 내역 CSV 기록
├── main.py                  # 메인 루프
├── backtest.py              # 백테스트 모듈 (선택)
└── requirements.txt         # pyupbit, pandas, ta 등
```

---

## 7. 핵심 라이브러리

```
pyupbit          # 업비트 API 래퍼
pandas           # 데이터 처리
ta               # 기술적 지표 계산 (볼린저, RSI, MACD)
schedule         # 주기적 작업 스케줄링
python-dotenv    # API 키 환경변수 관리
```

---

## 8. 메인 루프 흐름 (의사코드)

```python
while True:
    # 1) 코인 선정 (30분마다 갱신)
    targets = market_selector.get_top_volume_coins(n=5)

    for coin in targets:
        # 2) 5분봉 캔들 100개 조회
        candles = data_collector.get_candles(coin, interval=5, count=100)

        # 3) 지표 계산
        bb = calc_bollinger(candles, period=20, std=2)
        rsi = calc_rsi(candles, period=14)
        macd = calc_macd(candles, 12, 26, 9)
        vol = calc_volume_ratio(candles, period=20)

        # 4) 현재 보유 여부 확인
        if holding(coin):
            # 매도 판단
            if should_sell(coin, bb, rsi, entry_price, entry_time):
                order_executor.sell(coin)
        else:
            # 매수 판단
            signal = signal_engine.evaluate(bb, rsi, macd, vol)
            if signal.score >= 50 and risk_manager.can_buy():
                size = risk_manager.calc_position_size(signal.score)
                order_executor.buy(coin, size)

    sleep(5)  # 5초 대기
```

---

## 9. 설정 파일 구조 (config/settings.py)

```python
CONFIG = {
    # 업비트 API
    "access_key": "",       # .env에서 로드
    "secret_key": "",       # .env에서 로드

    # 코인 선정
    "market": "KRW",
    "top_n": 5,
    "min_trade_volume": 1_000_000_000,  # 최소 거래대금 10억
    "exclude_new_days": 7,
    "max_change_rate": 30,              # ±30% 초과 제외
    "max_spread_pct": 0.5,

    # 캔들/지표
    "candle_interval": 5,       # 5분봉
    "candle_count": 100,
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "volume_period": 20,
    "volume_threshold": 1.5,

    # 매매
    "buy_amount": 500_000,      # 1회 매매금 (원)
    "max_positions": 3,
    "total_budget_ratio": 0.8,

    # 리스크
    "stop_loss_pct": -2.0,
    "take_profit_mid": True,     # 중심선 익절
    "take_profit_upper": True,   # 상단밴드 익절
    "time_stop_minutes": 30,
    "cooldown_minutes": 15,
    "max_daily_trades": 20,
    "max_daily_loss": -50_000,

    # 시스템
    "loop_interval": 5,          # 메인루프 간격 (초)
    "market_refresh_interval": 1800,  # 코인 재선정 간격 (초)
}
```

---

## 10. 주의사항 및 팁

### 업비트 API 제한
- 초당 요청 제한: 분당 600회 (초당 10회)
- 주문 API: 초당 8회
- 캔들 조회: 초당 10회
- **rate limit 관리 필수** → 요청 간 sleep(0.1) 삽입

### 수수료 고려
- 업비트 거래 수수료: **0.05%** (매수/매도 각각)
- 왕복 수수료: 0.1%
- → 최소 0.1% 이상의 수익이 나야 본전

### 백테스트 우선
- 실전 투입 전 최소 1주일치 5분봉 데이터로 백테스트
- 승률 55% 이상 + 손익비 1.5:1 이상 확인 후 실전 전환

### 실전 전환 순서
1. 페이퍼 트레이딩 (로그만 기록, 실주문 X) → 3일
2. 최소금액 매매 (5,000원) → 3일
3. 목표 금액 매매 → 실전
