"""Abstract base class for broker implementations.

All broker implementations (Mock, Alpaca, IBKR, etc.) must inherit from
BaseBroker and implement the abstract methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from .models import (
    Order,
    OrderResult,
    Position,
    AccountInfo,
    PerformanceSummary,
)


class BaseBroker(ABC):
    """Abstract base class for all broker implementations.

    This interface defines the contract that all brokers must implement,
    allowing the trading system to work with any broker by simply
    swapping the implementation.

    Example:
        # Using mock broker for testing
        broker = MockBroker(initial_cash=100000)

        # Later, switch to real broker
        broker = AlpacaBroker(api_key="...", secret_key="...")

        # Same interface for both
        result = broker.submit_order(order)
    """

    @abstractmethod
    def submit_order(self, order: Order) -> OrderResult:
        """Submit an order for execution.

        Args:
            order: The order to submit

        Returns:
            OrderResult containing the execution details

        Raises:
            BrokerError: If the order cannot be submitted
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order.

        Args:
            order_id: The broker-assigned order ID to cancel

        Returns:
            True if cancellation was successful, False otherwise
        """
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[OrderResult]:
        """Get the current status of an order.

        Args:
            order_id: The broker-assigned order ID

        Returns:
            OrderResult if found, None otherwise
        """
        pass

    @abstractmethod
    def get_orders(self, status: Optional[str] = None) -> List[OrderResult]:
        """Get all orders, optionally filtered by status.

        Args:
            status: Optional status filter (e.g., "open", "closed", "all")

        Returns:
            List of OrderResult objects
        """
        pass

    @abstractmethod
    def get_position(self, ticker: str) -> Optional[Position]:
        """Get the current position for a specific ticker.

        Args:
            ticker: The symbol to look up

        Returns:
            Position if found, None otherwise
        """
        pass

    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        """Get all current positions.

        Returns:
            Dictionary mapping ticker symbols to Position objects
        """
        pass

    @abstractmethod
    def get_account(self) -> AccountInfo:
        """Get current account information.

        Returns:
            AccountInfo with cash, equity, margin details
        """
        pass

    @abstractmethod
    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get the current market price for a ticker.

        Args:
            ticker: The symbol to look up

        Returns:
            Current price if available, None otherwise
        """
        pass

    def close_position(self, ticker: str) -> Optional[OrderResult]:
        """Close an entire position for a ticker.

        Default implementation creates a market order to close.
        Brokers may override for more efficient handling.

        Args:
            ticker: The symbol to close

        Returns:
            OrderResult if position existed and order submitted, None otherwise
        """
        position = self.get_position(ticker)
        if position is None or position.quantity == 0:
            return None

        from .models import OrderSide, OrderType, PositionSide

        # Determine the order needed to close
        if position.side == PositionSide.LONG:
            side = OrderSide.SELL
        else:
            side = OrderSide.BUY

        order = Order(
            ticker=ticker,
            side=side,
            quantity=abs(position.quantity),
            order_type=OrderType.MARKET,
            position_side=position.side,
        )

        return self.submit_order(order)

    def close_all_positions(self) -> List[OrderResult]:
        """Close all open positions.

        Returns:
            List of OrderResult for each closed position
        """
        results = []
        for ticker in self.get_positions():
            result = self.close_position(ticker)
            if result:
                results.append(result)
        return results


class BrokerError(Exception):
    """Base exception for broker-related errors."""

    pass


class InsufficientFundsError(BrokerError):
    """Raised when there are insufficient funds for an order."""

    pass


class OrderRejectedError(BrokerError):
    """Raised when an order is rejected by the broker."""

    pass


class ConnectionError(BrokerError):
    """Raised when unable to connect to the broker."""

    pass
