"""Broker factory for creating broker instances based on configuration.

This module provides a factory function that creates the appropriate
broker instance based on environment variables or explicit configuration.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any, Callable, Dict, Optional

from .base import BaseBroker, BrokerError
from .mock import MockBroker


class BrokerType(str, Enum):
    """Supported broker types."""

    MOCK = "mock"
    ALPACA = "alpaca"
    IBKR = "ibkr"
    # Add more brokers as needed


def create_broker(
    broker_type: Optional[BrokerType] = None,
    *,
    initial_cash: Optional[float] = None,
    margin_requirement: Optional[float] = None,
    slippage: Optional[float] = None,
    max_slippage: Optional[float] = None,
    price_provider: Optional[Callable[[str], Optional[float]]] = None,
    **kwargs: Any,
) -> BaseBroker:
    """Create a broker instance based on type and configuration.

    If broker_type is not specified, it will be determined from the
    BROKER_TYPE environment variable, defaulting to MOCK.

    Settings can be configured via:
    1. Function arguments (highest priority)
    2. Environment variables
    3. Default values (lowest priority)

    Environment variables:
        BROKER_TYPE: mock, alpaca, ibkr
        BROKER_INITIAL_CASH: Starting cash (default: 1000000)
        BROKER_MARGIN_REQUIREMENT: Margin ratio (default: 0.5)
        BROKER_SLIPPAGE: Slippage percentage (default: 0.0)
        BROKER_MAX_SLIPPAGE: Max slippage protection (default: 0.005 = 0.5%)

    Args:
        broker_type: Type of broker to create (or auto-detect from env)
        initial_cash: Starting cash balance (for mock broker)
        margin_requirement: Margin requirement ratio (for mock broker)
        slippage: Simulated slippage percentage (for mock broker)
        max_slippage: Max slippage protection - reject orders exceeding this (for mock broker)
        price_provider: Function to get current prices
        **kwargs: Additional broker-specific configuration

    Returns:
        BaseBroker instance

    Raises:
        BrokerError: If the broker type is not supported or configuration is invalid

    Example:
        # Create from environment variables (reads .env)
        broker = create_broker()

        # Override with specific settings
        broker = create_broker(initial_cash=500_000)
    """
    # Determine broker type from environment if not specified
    if broker_type is None:
        env_broker = os.environ.get("BROKER_TYPE", "mock").lower()
        try:
            broker_type = BrokerType(env_broker)
        except ValueError:
            raise BrokerError(f"Unknown broker type: {env_broker}. " f"Supported types: {[b.value for b in BrokerType]}")

    # Read settings from environment with fallback to defaults
    if initial_cash is None:
        initial_cash = float(os.environ.get("BROKER_INITIAL_CASH", "1000000"))
    if margin_requirement is None:
        margin_requirement = float(os.environ.get("BROKER_MARGIN_REQUIREMENT", "0.5"))
    if slippage is None:
        slippage = float(os.environ.get("BROKER_SLIPPAGE", "0.0"))
    if max_slippage is None:
        max_slippage = float(os.environ.get("BROKER_MAX_SLIPPAGE", "0.005"))

    # Create the appropriate broker
    if broker_type == BrokerType.MOCK:
        return MockBroker(
            initial_cash=initial_cash,
            margin_requirement=margin_requirement,
            slippage=slippage,
            max_slippage=max_slippage,
            price_provider=price_provider,
        )

    elif broker_type == BrokerType.ALPACA:
        return _create_alpaca_broker(**kwargs)

    elif broker_type == BrokerType.IBKR:
        return _create_ibkr_broker(**kwargs)

    else:
        raise BrokerError(f"Broker type not implemented: {broker_type}")


def _create_alpaca_broker(**kwargs: Any) -> BaseBroker:
    """Create an Alpaca broker instance.

    Requires ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.
    Optionally, set ALPACA_PAPER=true for paper trading (default).

    This is a placeholder that will be implemented when Alpaca support is added.
    """
    # Check for required environment variables
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    is_paper = os.environ.get("ALPACA_PAPER", "true").lower() == "true"

    if not api_key or not secret_key:
        raise BrokerError("Alpaca broker requires ALPACA_API_KEY and ALPACA_SECRET_KEY " "environment variables")

    # TODO: Implement AlpacaBroker
    # from .alpaca import AlpacaBroker
    # return AlpacaBroker(api_key=api_key, secret_key=secret_key, paper=is_paper)

    raise BrokerError("Alpaca broker is not yet implemented. " "Use BROKER_TYPE=mock for paper trading.")


def _create_ibkr_broker(**kwargs: Any) -> BaseBroker:
    """Create an Interactive Brokers instance.

    Requires IBKR_HOST, IBKR_PORT, and IBKR_CLIENT_ID environment variables.

    This is a placeholder that will be implemented when IBKR support is added.
    """
    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_PORT", "7497"))  # 7497 = paper, 7496 = live
    client_id = int(os.environ.get("IBKR_CLIENT_ID", "1"))

    # TODO: Implement IBKRBroker
    # from .ibkr import IBKRBroker
    # return IBKRBroker(host=host, port=port, client_id=client_id)

    raise BrokerError("Interactive Brokers is not yet implemented. " "Use BROKER_TYPE=mock for paper trading.")


# Registry for custom broker implementations
_broker_registry: Dict[str, type] = {}


def register_broker(name: str, broker_class: type) -> None:
    """Register a custom broker implementation.

    This allows users to add their own broker implementations without
    modifying the core code.

    Args:
        name: Name to register the broker under
        broker_class: Class that implements BaseBroker

    Example:
        class MyCustomBroker(BaseBroker):
            ...

        register_broker("custom", MyCustomBroker)
        broker = create_broker(BrokerType("custom"))
    """
    if not issubclass(broker_class, BaseBroker):
        raise TypeError(f"{broker_class} must inherit from BaseBroker")
    _broker_registry[name] = broker_class
