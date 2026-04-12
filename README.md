# 업비트 자동매매 시스템

Django 기반 업비트 암호화폐 자동매매 웹 애플리케이션입니다. 실시간 시장 분석, 자동 매수/매도, 리스크 관리 기능을 포함하며, PC와 모바일에서 원격으로 제어할 수 있습니다.

## 기술 스택

| 구분 | 기술 |
|------|------|
| 백엔드 | Django 5.1 + Django REST Framework |
| 데이터베이스 | SQLite3 |
| 외부 API | 업비트 REST API (JWT 인증) |
| 프론트엔드 | HTML + Vanilla JS (반응형) |
| 원격 접속 | Tailscale VPN |

## 핵심 기능

### 자동매매 엔진
- 1초 간격 매매 루프 (별도 데몬 스레드)
- 최대 3개 코인 동시 보유
- 프로그램 재시작 시 DB에서 활성 거래 자동 복원
- 사용자 수동 매도 자동 감지

### 종목 선정 (3단계 필터링)
1. **1차** - 전일 대비 상승률 상위 10개 선별
2. **2차** - 호가 분석 (매수세 > 매도세 x 1.5, 스프레드 < 0.1%)
3. **3차** - 거래대금 상위 5개 중 현재가 x 거래대금 최고 종목 선정

### 시장 강도 분석
3가지 지표를 결합하여 시장 상태(상승/하락/보합)를 판단합니다:
- BTC/ETH 평균 변동률
- 전체 시장 거래량 변화 (24시간 대비)
- 상승/하락 코인 비율

2개 이상 동일 방향이면 해당 시장 상태로 결정됩니다.

### 매도 전략

| 조건 | 동작 |
|------|------|
| 수익 1% + 보합/하락장 | 즉시 매도 |
| 수익 2% 이상 | 트레일링 스탑 (최고가 대비 1% 하락 시 매도) |
| 보유 5분(상승장) / 10분 | 수익 1% 이상이면 시간 매도 |
| 손실 -2% | 일반 손절 |
| 손실 -4% | 고변동성(5%+) 종목 손절 |

### 안전장치
- KRW 잔고 초과 방지 (자동 조정)
- 주문 실패 종목 자동 차단 (FailedMarket DB)
- 매도 후 동일 종목 10분간 재매수 제한
- 잔고 10,000원 미만 시 매수 중단
- 에러 발생 시 최대 3회 자동 재시도

### 기술적 지표
RSI, MACD, 스토캐스틱, EMA, 볼린저밴드, ATR

## 프로젝트 구조

```
├── autocode/                # Django 프로젝트 설정
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── trading/                 # 메인 트레이딩 앱
│   ├── models.py            # DB 모델 (TradeRecord, FailedMarket 등)
│   ├── upbit_client.py      # 업비트 API 클라이언트 (JWT 인증)
│   ├── indicators.py        # 기술적 지표 계산
│   ├── market_analyzer.py   # 시장 강도 분석
│   ├── coin_selector.py     # 3단계 종목 선정
│   ├── auto_trader.py       # 자동매매 엔진
│   ├── views.py             # API 엔드포인트
│   ├── urls.py              # URL 라우팅
│   ├── templates/           # 대시보드 HTML
│   └── static/              # JavaScript
├── manage.py
├── requirements.txt
└── .env.example             # API 키 템플릿
```

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. API 키 설정

[업비트 Open API](https://upbit.com/mypage/open_api_management)에서 키를 발급받은 뒤 `.env` 파일을 생성합니다:

```bash
cp .env.example .env
```

```env
UPBIT_API_KEY=발급받은_access_key
UPBIT_SECRET_KEY=발급받은_secret_key
DJANGO_SECRET_KEY=임의의_랜덤_문자열
DEBUG=True
```

API 키 권한: **자산조회 + 주문** 허용 필요

### 3. DB 초기화

```bash
python manage.py migrate
```

### 4. 서버 실행

```bash
# 로컬 전용
python manage.py runserver

# Tailscale 원격 접속 허용
python manage.py runserver 0.0.0.0:8000
```

브라우저에서 `http://localhost:8000` 접속

## 원격 접속 (Tailscale)

1. PC와 핸드폰에 [Tailscale](https://tailscale.com) 설치 후 같은 계정으로 로그인
2. 서버를 `0.0.0.0:8000`으로 실행
3. 핸드폰 브라우저에서 `http://{PC의 Tailscale IP}:8000` 접속

## API 엔드포인트

| URL | 기능 |
|-----|------|
| `/` | 대시보드 |
| `/auto_trade/start/?budget=N` | 자동매매 시작 (N원) |
| `/auto_trade/stop/` | 자동매매 중지 |
| `/api/fetch_account_data/` | 계좌 정보 |
| `/api/fetch_coin_data/` | 코인 시세 |
| `/api/trade_logs/` | 거래 로그 |
| `/api/check_auto_trading/` | 실행 상태 |
| `/api/get_market_volume/` | 시장 상태 |
| `/api/getRecntTradeLog/` | 최근 매도 내역 |
| `/api/recentProfitLog/` | 수익 로그 |

## 수수료

| 항목 | 값 |
|------|-----|
| 수수료율 | 0.05% (매수/매도 각각) |
| 왕복 수수료 | 0.1% |
| 최소 수익 | 0.1% 이상이어야 본전 |

## 주의사항

- 자동매매는 항상 손실 위험이 있으므로 감당 가능한 금액으로 운용하세요
- API 키는 절대 외부에 노출하지 마세요
- 업비트 API 요청 제한: 분당 600회
- PC가 켜져 있어야 봇이 동작합니다
