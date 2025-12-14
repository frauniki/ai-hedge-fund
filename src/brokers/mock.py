"""Mock broker implementation for paper trading and backtesting.

This broker simulates order execution without actually placing trades.
It maintains internal state for positions and cash, making it perfect
for testing strategies before going live.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional
from uuid import uuid4

from .base import BaseBroker, InsufficientFundsError, OrderRejectedError
from .models import (
    AccountInfo,
    Order,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PerformanceSummary,
    Position,
    PositionSide,
)

DEFAULT_STATE_FILE = Path("data/broker_state.json")


class MockBroker(BaseBroker):
    """Mock broker for paper trading and backtesting.

    Simulates order execution with configurable behavior for testing
    different scenarios (slippage, partial fills, rejections, etc.)

    Attributes:
        initial_cash: Starting cash balance
        margin_requirement: Required margin ratio for short positions
        slippage: Simulated slippage as a percentage (0.0 = no slippage)
        price_provider: Optional function to get current prices
    """

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        margin_requirement: float = 0.5,
        slippage: float = 0.0,
        max_slippage: float = 0.005,  # Default 0.5% max slippage protection
        price_provider: Optional[Callable[[str], Optional[float]]] = None,
        state_file: Optional[Path] = None,
        auto_save: bool = True,
    ) -> None:
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._margin_requirement = margin_requirement
        self._margin_used = 0.0
        self._slippage = slippage
        self._max_slippage = max_slippage
        self._price_provider = price_provider
        self._state_file = state_file or DEFAULT_STATE_FILE
        self._auto_save = auto_save

        # Internal state
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, OrderResult] = {}
        self._prices: Dict[str, float] = {}  # Manual price cache

    def set_price(self, ticker: str, price: float) -> None:
        """Manually set the current price for a ticker.

        Useful for backtesting where prices are known in advance.

        Args:
            ticker: Symbol to set price for
            price: The price to use
        """
        self._prices[ticker] = price

    def set_prices(self, prices: Dict[str, float]) -> None:
        """Set prices for multiple tickers at once.

        Args:
            prices: Dictionary mapping tickers to prices
        """
        self._prices.update(prices)

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get the current price for a ticker.

        First checks manual price cache, then falls back to price_provider.

        Args:
            ticker: Symbol to look up

        Returns:
            Current price if available, None otherwise
        """
        if ticker in self._prices:
            return self._prices[ticker]
        if self._price_provider:
            return self._price_provider(ticker)
        return None

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply simulated slippage to execution price.

        Args:
            price: Base price
            side: Order side (slippage direction depends on side)

        Returns:
            Price adjusted for slippage
        """
        if self._slippage == 0:
            return price
        # Slippage works against the trader
        if side == OrderSide.BUY:
            return price * (1 + self._slippage)
        else:
            return price * (1 - self._slippage)

    def submit_order(self, order: Order) -> OrderResult:
        """Submit an order for simulated execution.

        For market orders, executes immediately at current price.
        For limit orders, only executes if price condition is met.

        Args:
            order: The order to submit

        Returns:
            OrderResult with execution details
        """
        current_price = self.get_current_price(order.ticker)

        if current_price is None:
            return self._create_rejected_result(order, f"No price available for {order.ticker}")

        # Determine execution price based on order type
        if order.order_type == OrderType.MARKET:
            exec_price = self._apply_slippage(current_price, order.side)
            # Check max slippage protection
            if self._max_slippage > 0:
                actual_slippage = abs(exec_price - current_price) / current_price
                if actual_slippage > self._max_slippage:
                    return self._create_rejected_result(
                        order,
                        f"Slippage {actual_slippage:.2%} exceeds max {self._max_slippage:.2%}",
                    )
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                return self._create_rejected_result(order, "Limit price required")
            # Check if limit price is executable
            if order.side == OrderSide.BUY and current_price > order.limit_price:
                # Buy limit not reached - order pending
                return self._create_pending_result(order)
            elif order.side == OrderSide.SELL and current_price < order.limit_price:
                # Sell limit not reached - order pending
                return self._create_pending_result(order)
            exec_price = order.limit_price
        else:
            # For other order types, just use market price for now
            exec_price = self._apply_slippage(current_price, order.side)

        # Execute the order based on position side
        try:
            if order.position_side == PositionSide.LONG:
                if order.side == OrderSide.BUY:
                    filled_qty = self._execute_long_buy(order.ticker, order.quantity, exec_price)
                else:  # SELL
                    filled_qty = self._execute_long_sell(order.ticker, order.quantity, exec_price)
            else:  # SHORT
                if order.side == OrderSide.SELL:
                    filled_qty = self._execute_short_open(order.ticker, order.quantity, exec_price)
                else:  # BUY (cover)
                    filled_qty = self._execute_short_cover(order.ticker, order.quantity, exec_price)
        except InsufficientFundsError as e:
            return self._create_rejected_result(order, str(e))

        # Create result
        if filled_qty == 0:
            result = self._create_rejected_result(order, "No quantity filled")
        elif filled_qty < order.quantity:
            result = self._create_partial_result(order, filled_qty, exec_price)
        else:
            result = self._create_filled_result(order, filled_qty, exec_price)

        # Store the result
        self._orders[result.order_id] = result
        return result

    def _execute_long_buy(self, ticker: str, quantity: int, price: float) -> int:
        """Execute a long buy order."""
        cost = quantity * price
        if cost > self._cash:
            # Partial fill with available cash
            max_qty = int(self._cash / price) if price > 0 else 0
            if max_qty == 0:
                raise InsufficientFundsError(f"Insufficient cash for {ticker}: need {cost:.2f}, have {self._cash:.2f}")
            quantity = max_qty
            cost = quantity * price

        position = self._get_or_create_position(ticker, PositionSide.LONG)

        # Update average cost
        old_qty = position.quantity
        old_cost = position.average_cost
        new_qty = old_qty + quantity
        if new_qty > 0:
            position.average_cost = (old_cost * old_qty + price * quantity) / new_qty
        position.quantity = new_qty

        self._cash -= cost
        return quantity

    def _execute_long_sell(self, ticker: str, quantity: int, price: float) -> int:
        """Execute a long sell order."""
        position = self._positions.get(ticker)
        if position is None or position.side != PositionSide.LONG:
            return 0

        # Can only sell what we have
        quantity = min(quantity, position.quantity)
        if quantity <= 0:
            return 0

        # Calculate realized PnL
        realized_pnl = (price - position.average_cost) * quantity
        position.realized_pnl += realized_pnl
        position.quantity -= quantity

        self._cash += quantity * price

        # Remove position if fully closed
        if position.quantity == 0:
            del self._positions[ticker]

        return quantity

    def _execute_short_open(self, ticker: str, quantity: int, price: float) -> int:
        """Execute a short sell (open short position)."""
        proceeds = price * quantity
        margin_required = proceeds * self._margin_requirement

        if margin_required > self._cash:
            # Partial fill with available margin
            max_qty = int(self._cash / (price * self._margin_requirement))
            if max_qty == 0:
                raise InsufficientFundsError(f"Insufficient margin for short {ticker}: need {margin_required:.2f}")
            quantity = max_qty
            proceeds = price * quantity
            margin_required = proceeds * self._margin_requirement

        position = self._get_or_create_position(ticker, PositionSide.SHORT)

        # Update average cost (for short, this is the price we sold at)
        old_qty = abs(position.quantity)
        old_cost = position.average_cost
        new_qty = old_qty + quantity
        if new_qty > 0:
            position.average_cost = (old_cost * old_qty + price * quantity) / new_qty
        position.quantity = -new_qty  # Negative for short

        self._margin_used += margin_required
        self._cash += proceeds - margin_required

        return quantity

    def _execute_short_cover(self, ticker: str, quantity: int, price: float) -> int:
        """Execute a short cover (close short position)."""
        position = self._positions.get(ticker)
        if position is None or position.side != PositionSide.SHORT:
            return 0

        # Can only cover what we have shorted
        short_qty = abs(position.quantity)
        quantity = min(quantity, short_qty)
        if quantity <= 0:
            return 0

        cover_cost = quantity * price
        # Realized PnL for short: profit when buy back price < sell price
        realized_pnl = (position.average_cost - price) * quantity
        position.realized_pnl += realized_pnl

        # Release margin proportionally
        portion = quantity / short_qty
        margin_to_release = portion * (self._margin_used * short_qty / max(1, short_qty))
        # Simplified: just track that we covered
        margin_to_release = cover_cost * self._margin_requirement

        position.quantity += quantity  # Moves toward 0

        self._margin_used -= margin_to_release
        self._cash += margin_to_release - cover_cost

        # Remove position if fully closed
        if position.quantity == 0:
            del self._positions[ticker]

        return quantity

    def _get_or_create_position(self, ticker: str, side: PositionSide) -> Position:
        """Get existing position or create a new one."""
        if ticker not in self._positions:
            self._positions[ticker] = Position(
                ticker=ticker,
                quantity=0,
                side=side,
                average_cost=0.0,
            )
        return self._positions[ticker]

    def _create_filled_result(self, order: Order, quantity: int, price: float) -> OrderResult:
        """Create a filled order result."""
        return OrderResult(
            order_id=str(uuid4()),
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side,
            quantity_requested=order.quantity,
            quantity_filled=quantity,
            status=OrderStatus.FILLED,
            average_price=price,
            filled_at=datetime.now(),
        )

    def _create_partial_result(self, order: Order, quantity: int, price: float) -> OrderResult:
        """Create a partial fill order result."""
        return OrderResult(
            order_id=str(uuid4()),
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side,
            quantity_requested=order.quantity,
            quantity_filled=quantity,
            status=OrderStatus.PARTIAL,
            average_price=price,
            message=f"Partial fill: {quantity}/{order.quantity}",
        )

    def _create_rejected_result(self, order: Order, message: str) -> OrderResult:
        """Create a rejected order result."""
        return OrderResult(
            order_id=str(uuid4()),
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side,
            quantity_requested=order.quantity,
            quantity_filled=0,
            status=OrderStatus.REJECTED,
            message=message,
        )

    def _create_pending_result(self, order: Order) -> OrderResult:
        """Create a pending order result."""
        result = OrderResult(
            order_id=str(uuid4()),
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side,
            quantity_requested=order.quantity,
            quantity_filled=0,
            status=OrderStatus.PENDING,
            message="Order pending - limit price not reached",
        )
        self._orders[result.order_id] = result
        return result

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if order_id not in self._orders:
            return False
        order = self._orders[order_id]
        if order.is_terminal:
            return False
        order.status = OrderStatus.CANCELLED
        return True

    def get_order(self, order_id: str) -> Optional[OrderResult]:
        """Get order by ID."""
        return self._orders.get(order_id)

    def get_orders(self, status: Optional[str] = None) -> List[OrderResult]:
        """Get all orders, optionally filtered."""
        orders = list(self._orders.values())
        if status == "open":
            return [o for o in orders if not o.is_terminal]
        elif status == "closed":
            return [o for o in orders if o.is_terminal]
        return orders

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get position for a ticker."""
        position = self._positions.get(ticker)
        if position:
            # Update with current price
            price = self.get_current_price(ticker)
            if price:
                position.update_market_data(price)
        return position

    def get_positions(self) -> Dict[str, Position]:
        """Get all positions."""
        # Update all positions with current prices
        for ticker, position in self._positions.items():
            price = self.get_current_price(ticker)
            if price:
                position.update_market_data(price)
        return dict(self._positions)

    def get_account(self) -> AccountInfo:
        """Get account information."""
        # Calculate equity
        positions_value = sum(pos.market_value for pos in self._positions.values())
        equity = self._cash + positions_value

        return AccountInfo(
            account_id="mock-account",
            cash=self._cash,
            buying_power=self._cash - self._margin_used,
            equity=equity,
            margin_used=self._margin_used,
            margin_available=self._cash - self._margin_used,
            is_paper=True,
        )

    def reset(self) -> None:
        """Reset the broker to initial state.

        Useful for running multiple backtests.
        """
        self._cash = self._initial_cash
        self._margin_used = 0.0
        self._positions.clear()
        self._orders.clear()
        self._prices.clear()

    def get_performance_summary(self) -> PerformanceSummary:
        """Get a summary of trading performance.

        Returns:
            PerformanceSummary with P&L, equity, and trade statistics

        Example:
            summary = broker.get_performance_summary()
            print(summary)  # Human-readable output
            print(f"Return: {summary.total_pnl_percent:.2f}%")
        """
        # Update all positions with current prices
        positions = self.get_positions()

        # Calculate positions value and P&L
        positions_value = 0.0
        realized_pnl = 0.0
        unrealized_pnl = 0.0

        for pos in positions.values():
            positions_value += pos.market_value
            realized_pnl += pos.realized_pnl
            unrealized_pnl += pos.unrealized_pnl

        # Calculate equity and total P&L
        current_equity = self._cash + positions_value
        total_pnl = current_equity - self._initial_cash
        total_pnl_percent = (total_pnl / self._initial_cash) * 100 if self._initial_cash > 0 else 0.0

        # Count trades
        filled_orders = [o for o in self._orders.values() if o.status == OrderStatus.FILLED]
        total_trades = len(filled_orders)

        # Count winning/losing trades (simplified: based on realized P&L per position)
        winning_trades = 0
        losing_trades = 0
        for pos in positions.values():
            if pos.realized_pnl > 0:
                winning_trades += 1
            elif pos.realized_pnl < 0:
                losing_trades += 1

        win_rate = (winning_trades / (winning_trades + losing_trades) * 100) if (winning_trades + losing_trades) > 0 else 0.0

        return PerformanceSummary(
            initial_capital=self._initial_cash,
            current_equity=current_equity,
            cash=self._cash,
            positions_value=positions_value,
            total_pnl=total_pnl,
            total_pnl_percent=total_pnl_percent,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
        )

    def save_state(self, file_path: Optional[Path] = None) -> None:
        """Save broker state to a JSON file.

        Args:
            file_path: Path to save state to. Defaults to self._state_file.

        Example:
            broker.save_state()  # Saves to data/broker_state.json
            broker.save_state(Path("my_state.json"))
        """
        path = Path(file_path) if file_path else self._state_file
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize positions
        positions_data = {}
        for ticker, pos in self._positions.items():
            positions_data[ticker] = {
                "quantity": pos.quantity,
                "side": pos.side.value,
                "average_cost": pos.average_cost,
                "realized_pnl": pos.realized_pnl,
            }

        # Serialize orders
        orders_data = {}
        for order_id, order in self._orders.items():
            orders_data[order_id] = {
                "order_id": order.order_id,
                "client_order_id": order.client_order_id,
                "ticker": order.ticker,
                "side": order.side.value,
                "quantity_requested": order.quantity_requested,
                "quantity_filled": order.quantity_filled,
                "status": order.status.value,
                "average_price": order.average_price,
                "message": order.message,
                "submitted_at": order.submitted_at.isoformat(),
                "filled_at": order.filled_at.isoformat() if order.filled_at else None,
            }

        state = {
            "version": 1,
            "saved_at": datetime.now().isoformat(),
            "initial_cash": self._initial_cash,
            "cash": self._cash,
            "margin_requirement": self._margin_requirement,
            "margin_used": self._margin_used,
            "max_slippage": self._max_slippage,
            "positions": positions_data,
            "orders": orders_data,
            "prices": self._prices,
        }

        with open(path, "w") as f:
            json.dump(state, f, indent=2)

        print(f"State saved to {path}")

    def load_state(self, file_path: Optional[Path] = None) -> bool:
        """Load broker state from a JSON file.

        Args:
            file_path: Path to load state from. Defaults to self._state_file.

        Returns:
            True if state was loaded successfully, False otherwise.

        Example:
            broker.load_state()  # Loads from data/broker_state.json
        """
        path = Path(file_path) if file_path else self._state_file

        if not path.exists():
            print(f"No state file found at {path}")
            return False

        try:
            with open(path, "r") as f:
                state = json.load(f)

            # Restore basic state
            self._initial_cash = state["initial_cash"]
            self._cash = state["cash"]
            self._margin_requirement = state["margin_requirement"]
            self._margin_used = state["margin_used"]
            self._max_slippage = state.get("max_slippage", 0.005)
            self._prices = state.get("prices", {})

            # Restore positions
            self._positions = {}
            for ticker, pos_data in state.get("positions", {}).items():
                self._positions[ticker] = Position(
                    ticker=ticker,
                    quantity=pos_data["quantity"],
                    side=PositionSide(pos_data["side"]),
                    average_cost=pos_data["average_cost"],
                    realized_pnl=pos_data.get("realized_pnl", 0.0),
                )

            # Restore orders
            self._orders = {}
            for order_id, order_data in state.get("orders", {}).items():
                self._orders[order_id] = OrderResult(
                    order_id=order_data["order_id"],
                    client_order_id=order_data["client_order_id"],
                    ticker=order_data["ticker"],
                    side=OrderSide(order_data["side"]),
                    quantity_requested=order_data["quantity_requested"],
                    quantity_filled=order_data["quantity_filled"],
                    status=OrderStatus(order_data["status"]),
                    average_price=order_data.get("average_price"),
                    message=order_data.get("message"),
                    submitted_at=datetime.fromisoformat(order_data["submitted_at"]),
                    filled_at=datetime.fromisoformat(order_data["filled_at"]) if order_data.get("filled_at") else None,
                )

            print(f"State loaded from {path} (saved at {state.get('saved_at', 'unknown')})")
            return True

        except Exception as e:
            print(f"Error loading state: {e}")
            return False

    def _auto_save_state(self) -> None:
        """Auto-save state if enabled."""
        if self._auto_save:
            self.save_state()
