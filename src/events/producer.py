"""Event producer for publishing trading events to Redis."""

import json
import os
from datetime import datetime
from typing import Callable, Dict, List, Optional

import redis

from .models import EventType, PriceData, TradingEvent


class EventProducer:
    """Produces trading events and publishes them to Redis.

    Attributes:
        redis_client: Redis connection
        channel: Redis pub/sub channel name
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        channel: str = "trading_events",
    ) -> None:
        redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._redis = redis.from_url(redis_url)
        self._channel = channel
        self._last_prices: Dict[str, float] = {}

    def publish(self, event: TradingEvent) -> int:
        """Publish an event to the Redis channel.

        Args:
            event: The trading event to publish

        Returns:
            Number of subscribers that received the message
        """
        return self._redis.publish(self._channel, event.to_json())

    def publish_price_update(
        self,
        ticker: str,
        price: float,
        volume: Optional[int] = None,
        source: str = "price_monitor",
    ) -> Optional[TradingEvent]:
        """Publish a price update event.

        If the price has moved significantly since the last update,
        publishes a PRICE_ALERT event. Otherwise, publishes a PRICE_UPDATE.

        Args:
            ticker: Stock symbol
            price: Current price
            volume: Trading volume
            source: Event source identifier

        Returns:
            The published event, or None if no event was published
        """
        previous_price = self._last_prices.get(ticker)
        change_percent = None

        if previous_price is not None and previous_price > 0:
            change_percent = ((price - previous_price) / previous_price) * 100

        self._last_prices[ticker] = price

        price_data = PriceData(
            ticker=ticker,
            price=price,
            previous_price=previous_price,
            change_percent=change_percent,
            volume=volume,
        )

        # Determine event type based on price movement
        if price_data.is_significant_move:
            event_type = EventType.PRICE_ALERT
            priority = 10  # High priority for significant moves
        else:
            event_type = EventType.PRICE_UPDATE
            priority = 1

        event = TradingEvent(
            event_type=event_type,
            ticker=ticker,
            data=price_data.to_dict(),
            source=source,
            priority=priority,
        )

        self.publish(event)
        return event

    def publish_news(
        self,
        ticker: str,
        headline: str,
        sentiment: Optional[str] = None,
        url: Optional[str] = None,
        source: str = "news_monitor",
    ) -> TradingEvent:
        """Publish a news event.

        Args:
            ticker: Related stock symbol
            headline: News headline
            sentiment: Optional sentiment (positive/negative/neutral)
            url: Link to full article
            source: Event source identifier

        Returns:
            The published event
        """
        event = TradingEvent(
            event_type=EventType.NEWS,
            ticker=ticker,
            data={
                "headline": headline,
                "sentiment": sentiment,
                "url": url,
            },
            source=source,
            priority=5,
        )
        self.publish(event)
        return event

    def publish_trade_signal(
        self,
        ticker: str,
        signal: str,  # "buy", "sell", "short", "cover"
        confidence: float,
        reason: Optional[str] = None,
        source: str = "signal_generator",
    ) -> TradingEvent:
        """Publish a trade signal event.

        Args:
            ticker: Stock symbol
            signal: Trading signal (buy/sell/short/cover)
            confidence: Confidence level (0-100)
            reason: Reason for the signal
            source: Event source identifier

        Returns:
            The published event
        """
        event = TradingEvent(
            event_type=EventType.TRADE_SIGNAL,
            ticker=ticker,
            data={
                "signal": signal,
                "confidence": confidence,
                "reason": reason,
            },
            source=source,
            priority=10,
        )
        self.publish(event)
        return event

    def publish_scheduled(
        self,
        tickers: List[str],
        source: str = "scheduler",
    ) -> TradingEvent:
        """Publish a scheduled analysis event.

        Args:
            tickers: List of tickers to analyze
            source: Event source identifier

        Returns:
            The published event
        """
        event = TradingEvent(
            event_type=EventType.SCHEDULED,
            data={"tickers": tickers},
            source=source,
            priority=5,
        )
        self.publish(event)
        return event

    def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            return self._redis.ping()
        except redis.ConnectionError:
            return False
