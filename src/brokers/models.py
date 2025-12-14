"""Data models for broker operations.

These models provide a unified interface for order management
across different broker implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class OrderSide(str, Enum):
    """Order side - buy or sell."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type for execution."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order execution status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PositionSide(str, Enum):
    """Position side - long or short."""

    LONG = "long"
    SHORT = "short"


@dataclass
class Order:
    """Represents an order to be submitted to a broker.

    Attributes:
        ticker: Symbol of the security to trade
        side: Buy or sell
        quantity: Number of shares to trade
        order_type: Market, limit, stop, etc.
        limit_price: Price for limit orders (required if order_type is LIMIT)
        stop_price: Price for stop orders (required if order_type is STOP)
        position_side: Whether this is for a long or short position
        client_order_id: Optional client-generated order ID
        time_in_force: How long order remains active (default: day)
    """

    ticker: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    position_side: PositionSide = PositionSide.LONG
    client_order_id: str = field(default_factory=lambda: str(uuid4()))
    time_in_force: str = "day"

    def __post_init__(self):
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders")
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("stop_price is required for STOP orders")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass
class OrderResult:
    """Result of an order submission/execution.

    Attributes:
        order_id: Broker-assigned order ID
        client_order_id: Client-generated order ID
        ticker: Symbol of the security
        side: Buy or sell
        quantity_requested: Original quantity requested
        quantity_filled: Actual quantity filled
        status: Current order status
        average_price: Average fill price (None if not filled)
        message: Optional status message or error description
        submitted_at: When the order was submitted
        filled_at: When the order was filled (None if not filled)
    """

    order_id: str
    client_order_id: str
    ticker: str
    side: OrderSide
    quantity_requested: int
    quantity_filled: int
    status: OrderStatus
    average_price: Optional[float] = None
    message: Optional[str] = None
    submitted_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == OrderStatus.FILLED

    @property
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state (no further updates expected)."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        )


@dataclass
class Position:
    """Represents a position held in the portfolio.

    Attributes:
        ticker: Symbol of the security
        quantity: Number of shares (positive for long, negative for short)
        side: Long or short position
        average_cost: Average cost basis per share
        current_price: Current market price
        market_value: Current market value of the position
        unrealized_pnl: Unrealized profit/loss
        realized_pnl: Realized profit/loss from closed trades
    """

    ticker: str
    quantity: int
    side: PositionSide
    average_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    def update_market_data(self, current_price: float) -> None:
        """Update position with current market price."""
        self.current_price = current_price
        self.market_value = abs(self.quantity) * current_price
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.average_cost) * self.quantity
        else:  # SHORT
            self.unrealized_pnl = (self.average_cost - current_price) * abs(self.quantity)


@dataclass
class AccountInfo:
    """Account information from the broker.

    Attributes:
        account_id: Broker account identifier
        cash: Available cash balance
        buying_power: Total buying power (including margin)
        equity: Total account equity
        margin_used: Margin currently in use
        margin_available: Available margin
        day_trade_count: Number of day trades in period (for PDT rule)
        is_paper: Whether this is a paper trading account
    """

    account_id: str
    cash: float
    buying_power: float
    equity: float
    margin_used: float = 0.0
    margin_available: float = 0.0
    day_trade_count: int = 0
    is_paper: bool = True


@dataclass
class PerformanceSummary:
    """Summary of trading performance.

    Attributes:
        initial_capital: Starting capital
        current_equity: Current total equity (cash + positions value)
        cash: Current cash balance
        positions_value: Total market value of open positions
        total_pnl: Total profit/loss (realized + unrealized)
        total_pnl_percent: Total P&L as percentage of initial capital
        realized_pnl: Sum of realized P&L from closed trades
        unrealized_pnl: Sum of unrealized P&L from open positions
        total_trades: Total number of trades executed
        winning_trades: Number of profitable trades
        losing_trades: Number of losing trades
        win_rate: Percentage of winning trades
    """

    initial_capital: float
    current_equity: float
    cash: float
    positions_value: float
    total_pnl: float
    total_pnl_percent: float
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0

    def __str__(self) -> str:
        """Human-readable summary."""
        sign = "+" if self.total_pnl >= 0 else ""
        return (
            f"=== Performance Summary ===\n"
            f"Initial Capital:  ${self.initial_capital:,.2f}\n"
            f"Current Equity:   ${self.current_equity:,.2f}\n"
            f"  - Cash:         ${self.cash:,.2f}\n"
            f"  - Positions:    ${self.positions_value:,.2f}\n"
            f"---------------------------\n"
            f"Total P&L:        {sign}${self.total_pnl:,.2f} ({sign}{self.total_pnl_percent:.2f}%)\n"
            f"  - Realized:     ${self.realized_pnl:,.2f}\n"
            f"  - Unrealized:   ${self.unrealized_pnl:,.2f}\n"
            f"---------------------------\n"
            f"Trades: {self.total_trades} (Win: {self.winning_trades}, Lose: {self.losing_trades})\n"
            f"Win Rate: {self.win_rate:.1f}%"
        )
