"""Configuration management for AI Hedge Fund.

Loads and validates configuration from YAML files.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class ModelConfig:
    """LLM model configuration."""

    name: str = "openai/gpt-oss-20b:free"
    provider: str = "OpenRouter"


@dataclass
class RedisConfig:
    """Redis configuration."""

    url: str = "redis://localhost:6379"
    channel: str = "trading_events"

    def __post_init__(self):
        # Allow environment variable override for Docker compatibility
        env_url = os.getenv("REDIS_URL")
        if env_url:
            self.url = env_url


@dataclass
class BrokerConfig:
    """Broker configuration."""

    type: str = "mock"
    initial_cash: float = 1_000_000
    margin_requirement: float = 0.5
    slippage: float = 0.001
    max_slippage: float = 0.005


@dataclass
class ProducerConfig:
    """Event producer configuration (financialdatasets)."""

    interval: int = 300
    alert_threshold: float = 2.0


@dataclass
class MassiveConfig:
    """Massive.com producer configuration."""

    mode: str = "polling"  # polling or websocket
    interval: int = 300
    alert_threshold: float = 2.0
    rate_limit: int = 15  # seconds between API calls (free tier: 5 calls/min)


@dataclass
class ConsumerConfig:
    """Event consumer configuration."""

    dry_run: bool = False
    min_confidence: int = 50


@dataclass
class MarketConfig:
    """Market hours configuration."""

    timezone: str = "US/Eastern"
    open: str = "09:30"
    close: str = "16:00"
    holidays: List[str] = field(default_factory=list)


@dataclass
class TradingConfig:
    """Main trading configuration."""

    tickers: List[str] = field(default_factory=lambda: ["AAPL", "MSFT", "NVDA"])
    model: ModelConfig = field(default_factory=ModelConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    producer: ProducerConfig = field(default_factory=ProducerConfig)
    massive: MassiveConfig = field(default_factory=MassiveConfig)
    consumer: ConsumerConfig = field(default_factory=ConsumerConfig)
    market: MarketConfig = field(default_factory=MarketConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TradingConfig":
        """Load configuration from a YAML file.

        Args:
            path: Path to the YAML config file

        Returns:
            TradingConfig instance
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data or {})

    @classmethod
    def from_dict(cls, data: dict) -> "TradingConfig":
        """Create configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            TradingConfig instance
        """
        return cls(
            tickers=data.get("tickers", ["AAPL", "MSFT", "NVDA"]),
            model=ModelConfig(**data.get("model", {})),
            redis=RedisConfig(**data.get("redis", {})),
            broker=BrokerConfig(**data.get("broker", {})),
            producer=ProducerConfig(**data.get("producer", {})),
            massive=MassiveConfig(**data.get("massive", {})),
            consumer=ConsumerConfig(**data.get("consumer", {})),
            market=MarketConfig(**data.get("market", {})),
        )

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            "tickers": self.tickers,
            "model": {"name": self.model.name, "provider": self.model.provider},
            "redis": {"url": self.redis.url, "channel": self.redis.channel},
            "broker": {
                "type": self.broker.type,
                "initial_cash": self.broker.initial_cash,
                "margin_requirement": self.broker.margin_requirement,
                "slippage": self.broker.slippage,
                "max_slippage": self.broker.max_slippage,
            },
            "producer": {
                "interval": self.producer.interval,
                "alert_threshold": self.producer.alert_threshold,
            },
            "massive": {
                "mode": self.massive.mode,
                "interval": self.massive.interval,
                "alert_threshold": self.massive.alert_threshold,
                "rate_limit": self.massive.rate_limit,
            },
            "consumer": {
                "dry_run": self.consumer.dry_run,
                "min_confidence": self.consumer.min_confidence,
            },
            "market": {
                "timezone": self.market.timezone,
                "open": self.market.open,
                "close": self.market.close,
                "holidays": self.market.holidays,
            },
        }


# Default config file locations
DEFAULT_CONFIG_PATHS = [
    Path("config/trading.yaml"),
    Path("trading.yaml"),
    Path.home() / ".config" / "ai-hedge-fund" / "trading.yaml",
]


def load_config(path: Optional[str | Path] = None) -> TradingConfig:
    """Load trading configuration.

    Searches for config file in the following order:
    1. Explicit path argument
    2. CONFIG_PATH environment variable
    3. Default locations (config/trading.yaml, trading.yaml, ~/.config/ai-hedge-fund/trading.yaml)
    4. Returns default config if no file found

    Args:
        path: Optional explicit path to config file

    Returns:
        TradingConfig instance
    """
    # Check explicit path
    if path:
        return TradingConfig.from_yaml(path)

    # Check environment variable
    env_path = os.getenv("CONFIG_PATH")
    if env_path:
        return TradingConfig.from_yaml(env_path)

    # Check default locations
    for default_path in DEFAULT_CONFIG_PATHS:
        if default_path.exists():
            return TradingConfig.from_yaml(default_path)

    # Return default config
    return TradingConfig()
