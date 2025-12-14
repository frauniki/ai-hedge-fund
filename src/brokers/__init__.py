"""Broker abstraction layer for order execution.

This module provides a pluggable broker interface that allows
switching between mock (paper trading) and real brokers (Alpaca, IBKR, etc.)
"""

from .base import BaseBroker, BrokerError, InsufficientFundsError, OrderRejectedError
from .models import (
    Order,
    OrderResult,
    OrderSide,
    OrderType,
    OrderStatus,
    Position,
    PositionSide,
    AccountInfo,
    PerformanceSummary,
)
from .mock import MockBroker
from .factory import create_broker, BrokerType

__all__ = [
    "BaseBroker",
    "BrokerError",
    "InsufficientFundsError",
    "OrderRejectedError",
    "Order",
    "OrderResult",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "Position",
    "PositionSide",
    "AccountInfo",
    "PerformanceSummary",
    "MockBroker",
    "create_broker",
    "BrokerType",
]
