from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from .portfolio import Portfolio
from .types import ActionLiteral, Action

if TYPE_CHECKING:
    from src.brokers import BaseBroker, OrderResult


class TradeExecutor:
    """Executes trades against a Portfolio or Broker.

    Supports two modes:
    1. Legacy mode: Direct portfolio manipulation (for backtesting compatibility)
    2. Broker mode: Execute through a broker interface (for paper/live trading)

    Example:
        # Legacy mode (backtesting)
        executor = TradeExecutor()
        executor.execute_trade("AAPL", "buy", 100, 150.0, portfolio)

        # Broker mode (live trading)
        from src.brokers import create_broker
        broker = create_broker()
        executor = TradeExecutor(broker=broker)
        result = executor.execute_trade_via_broker("AAPL", "buy", 100)
    """

    def __init__(self, broker: Optional["BaseBroker"] = None) -> None:
        """Initialize TradeExecutor.

        Args:
            broker: Optional broker instance. If provided, enables broker-based
                    trading via execute_trade_via_broker().
        """
        self._broker = broker

    @property
    def broker(self) -> Optional["BaseBroker"]:
        """Get the broker instance."""
        return self._broker

    @broker.setter
    def broker(self, broker: Optional["BaseBroker"]) -> None:
        """Set the broker instance."""
        self._broker = broker

    def execute_trade(
        self,
        ticker: str,
        action: ActionLiteral,
        quantity: float,
        current_price: float,
        portfolio: Portfolio,
    ) -> int:
        """Execute a trade against a Portfolio (legacy mode).

        This method maintains backward compatibility with existing backtesting code.

        Args:
            ticker: Symbol to trade
            action: Action to take (buy, sell, short, cover, hold)
            quantity: Number of shares
            current_price: Current price per share
            portfolio: Portfolio instance to modify

        Returns:
            Number of shares actually traded
        """
        if quantity is None or quantity <= 0:
            return 0

        # Coerce to enum if strings provided
        try:
            action_enum = Action(action) if not isinstance(action, Action) else action
        except Exception:
            action_enum = Action.HOLD

        if action_enum == Action.BUY:
            return portfolio.apply_long_buy(ticker, int(quantity), float(current_price))
        if action_enum == Action.SELL:
            return portfolio.apply_long_sell(ticker, int(quantity), float(current_price))
        if action_enum == Action.SHORT:
            return portfolio.apply_short_open(ticker, int(quantity), float(current_price))
        if action_enum == Action.COVER:
            return portfolio.apply_short_cover(ticker, int(quantity), float(current_price))

        # hold or unknown action
        return 0

    def execute_trade_via_broker(
        self,
        ticker: str,
        action: ActionLiteral,
        quantity: int,
        current_price: Optional[float] = None,
        order_type: str = "market",
        limit_price: Optional[float] = None,
    ) -> Optional["OrderResult"]:
        """Execute a trade through the broker interface.

        This method is for paper trading and live trading scenarios.

        Args:
            ticker: Symbol to trade
            action: Action to take (buy, sell, short, cover, hold)
            quantity: Number of shares
            current_price: Current price (used to set broker's price for mock)
            order_type: Order type ("market" or "limit")
            limit_price: Price for limit orders

        Returns:
            OrderResult if order was submitted, None for hold/invalid actions

        Raises:
            RuntimeError: If no broker is configured
        """
        if self._broker is None:
            raise RuntimeError("No broker configured. Initialize TradeExecutor with a broker " "or use execute_trade() for portfolio-based execution.")

        if quantity is None or quantity <= 0:
            return None

        # Coerce to enum if strings provided
        try:
            action_enum = Action(action) if not isinstance(action, Action) else action
        except Exception:
            action_enum = Action.HOLD

        if action_enum == Action.HOLD:
            return None

        # Import here to avoid circular imports
        from src.brokers import Order, OrderSide, OrderType, PositionSide

        # Set the current price in broker (for mock broker)
        if current_price is not None:
            if hasattr(self._broker, "set_price"):
                self._broker.set_price(ticker, current_price)

        # Map action to order parameters
        if action_enum == Action.BUY:
            side = OrderSide.BUY
            position_side = PositionSide.LONG
        elif action_enum == Action.SELL:
            side = OrderSide.SELL
            position_side = PositionSide.LONG
        elif action_enum == Action.SHORT:
            side = OrderSide.SELL
            position_side = PositionSide.SHORT
        elif action_enum == Action.COVER:
            side = OrderSide.BUY
            position_side = PositionSide.SHORT
        else:
            return None

        # Create order
        broker_order_type = OrderType.LIMIT if order_type == "limit" else OrderType.MARKET
        order = Order(
            ticker=ticker,
            side=side,
            quantity=int(quantity),
            order_type=broker_order_type,
            limit_price=limit_price if broker_order_type == OrderType.LIMIT else None,
            position_side=position_side,
        )

        # Submit order
        return self._broker.submit_order(order)
