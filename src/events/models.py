"""Data models for trading events."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import json


class EventType(str, Enum):
    """Types of trading events."""

    PRICE_UPDATE = "price_update"
    PRICE_ALERT = "price_alert"  # Significant price movement
    NEWS = "news"
    SENTIMENT = "sentiment"
    TRADE_SIGNAL = "trade_signal"
    SCHEDULED = "scheduled"


@dataclass
class TradingEvent:
    """Represents a trading event to be processed.

    Attributes:
        event_type: Type of the event
        ticker: Stock symbol (if applicable)
        data: Event-specific data payload
        timestamp: When the event occurred
        source: Origin of the event (e.g., "alpaca", "tradingview", "scheduler")
        priority: Event priority (higher = more urgent)
        event_id: Unique event identifier
    """

    event_type: EventType
    ticker: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "unknown"
    priority: int = 0
    event_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S%f"))

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["timestamp"] = self.timestamp.isoformat()
        return json.dumps(d)

    @classmethod
    def from_json(cls, json_str: str) -> "TradingEvent":
        """Deserialize event from JSON string."""
        d = json.loads(json_str)
        d["event_type"] = EventType(d["event_type"])
        d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)

    def __str__(self) -> str:
        ticker_str = f" [{self.ticker}]" if self.ticker else ""
        return f"Event({self.event_type.value}{ticker_str} from {self.source})"


@dataclass
class PriceData:
    """Price data for a ticker."""

    ticker: str
    price: float
    previous_price: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_significant_move(self) -> bool:
        """Check if price moved significantly (>2%)."""
        if self.change_percent is None:
            return False
        return abs(self.change_percent) >= 2.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "change_percent": self.change_percent,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
        }
