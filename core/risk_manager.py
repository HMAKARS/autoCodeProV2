import time
from dataclasses import dataclass, field
from config.settings import CONFIG
from utils.upbit_client import UpbitClient
from utils.logger import logger


@dataclass
class Position:
    """보유 포지션 정보."""
    market: str
    entry_price: float
    volume: float
    entry_time: float  # timestamp


class RiskManager:
    """리스크 관리 모듈.

    포지션 사이징, 동시 보유 제한, 쿨다운, 일일 손실한도를 관리한다.
    """

    def __init__(self, client: UpbitClient):
        self.client = client
        self.positions: dict[str, Position] = {}  # market -> Position
        self.daily_trades: int = 0
        self.daily_pnl: float = 0.0
        self.daily_reset_date: str = ""
        self._cooldowns: dict[str, float] = {}  # market -> cooldown_until
        self._consecutive_losses: int = 0
        self._global_cooldown_until: float = 0.0

    def can_buy(self, market: str = "") -> bool:
        """매수 가능 여부 판단."""
        self._check_daily_reset()

        # 일일 손실한도 확인
        if self.daily_pnl <= CONFIG["max_daily_loss"]:
            logger.warning(
                "일일 손실한도 도달: %.0f원 <= %.0f원",
                self.daily_pnl, CONFIG["max_daily_loss"],
            )
            return False

        # 일일 거래 횟수 확인
        if self.daily_trades >= CONFIG["max_daily_trades"]:
            logger.warning("일일 거래횟수 초과: %d회", self.daily_trades)
            return False

        # 최대 동시 보유 확인
        if len(self.positions) >= CONFIG["max_positions"]:
            logger.debug("최대 보유 코인 수 도달: %d개", len(self.positions))
            return False

        # 글로벌 쿨다운 확인 (연속 손절 후)
        now = time.time()
        if now < self._global_cooldown_until:
            remaining = (self._global_cooldown_until - now) / 60
            logger.debug("글로벌 쿨다운 중: %.1f분 남음", remaining)
            return False

        # 개별 코인 쿨다운 확인
        if market and market in self._cooldowns:
            if now < self._cooldowns[market]:
                remaining = (self._cooldowns[market] - now) / 60
                logger.debug("%s 쿨다운 중: %.1f분 남음", market, remaining)
                return False

        # 총 투자한도 확인
        krw_balance = self.client.get_balance("KRW")
        total_balance = krw_balance  # 간소화: KRW 잔고 기준
        if krw_balance < CONFIG["buy_amount"] * 0.5:
            logger.debug("KRW 잔고 부족: %.0f원", krw_balance)
            return False

        return True

    def calc_position_size(self, score: int) -> float:
        """시그널 점수 기반 포지션 사이즈 계산.

        Args:
            score: 시그널 점수 (0~100)

        Returns:
            매수 금액 (KRW)
        """
        base_amount = CONFIG["buy_amount"]

        if score >= 70:
            return base_amount  # 풀 사이즈
        elif score >= 50:
            return base_amount * 0.5  # 하프 사이즈
        else:
            return 0.0

    def add_position(
        self, market: str, entry_price: float, volume: float
    ):
        """포지션 추가."""
        self.positions[market] = Position(
            market=market,
            entry_price=entry_price,
            volume=volume,
            entry_time=time.time(),
        )
        self.daily_trades += 1
        logger.info(
            "포지션 추가: %s price=%.2f vol=%.8f (보유 %d개)",
            market, entry_price, volume, len(self.positions),
        )

    def remove_position(self, market: str, pnl: float = 0.0):
        """포지션 제거 및 손익 반영."""
        if market in self.positions:
            del self.positions[market]
        self.daily_pnl += pnl
        self.daily_trades += 1

        # 손절 시 쿨다운 적용
        if pnl < 0:
            cooldown_sec = CONFIG["cooldown_minutes"] * 60
            self._cooldowns[market] = time.time() + cooldown_sec
            self._consecutive_losses += 1
            logger.info(
                "%s 손절 쿨다운 %d분 적용 (연속 %d회)",
                market, CONFIG["cooldown_minutes"], self._consecutive_losses,
            )

            # 연속 3회 손절 시 글로벌 쿨다운
            if self._consecutive_losses >= 3:
                self._global_cooldown_until = time.time() + (30 * 60)
                self._consecutive_losses = 0
                logger.warning("연속 3회 손절 - 전체 매매 30분 중단")
        else:
            self._consecutive_losses = 0

    def get_position(self, market: str) -> Position | None:
        """포지션 조회."""
        return self.positions.get(market)

    def get_holding_minutes(self, market: str) -> float:
        """보유 경과 시간 (분) 조회."""
        pos = self.positions.get(market)
        if not pos:
            return 0.0
        return (time.time() - pos.entry_time) / 60

    def sync_positions(self):
        """업비트 서버의 보유 코인과 로컬 포지션을 동기화."""
        holdings = self.client.get_holding_coins()
        server_markets = set()
        for h in holdings:
            market = f"KRW-{h['currency']}"
            server_markets.add(market)
            if market not in self.positions:
                self.positions[market] = Position(
                    market=market,
                    entry_price=h["avg_buy_price"],
                    volume=h["balance"],
                    entry_time=time.time(),
                )
                logger.info("기존 보유 포지션 동기화: %s", market)

        # 서버에 없는 포지션 제거
        local_markets = list(self.positions.keys())
        for market in local_markets:
            if market not in server_markets:
                del self.positions[market]
                logger.info("포지션 동기화 제거: %s", market)

    def _check_daily_reset(self):
        """일일 통계 초기화 (날짜 변경 시)."""
        import datetime
        today = datetime.date.today().isoformat()
        if self.daily_reset_date != today:
            self.daily_reset_date = today
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self._consecutive_losses = 0
            self._global_cooldown_until = 0.0
            logger.info("일일 통계 초기화: %s", today)
