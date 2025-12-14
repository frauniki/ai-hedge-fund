"""Base producer interface for price monitoring."""

import signal
import sys
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional

from src.config import TradingConfig
from src.events import EventProducer, EventType


def log(message: str) -> None:
    """Log message with timestamp."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}")


class BasePriceMonitor(ABC):
    """Abstract base class for price monitors."""

    name: str = "base"  # Override in subclass

    def __init__(self, config: TradingConfig, producer: EventProducer):
        self.config = config
        self.producer = producer
        self.last_prices: Dict[str, float] = {}
        self.running = False

    @property
    @abstractmethod
    def interval(self) -> int:
        """Return polling interval in seconds."""
        pass

    @property
    @abstractmethod
    def alert_threshold(self) -> float:
        """Return alert threshold percentage."""
        pass

    @property
    def rate_limit(self) -> int:
        """Return rate limit in seconds between API calls. Override if needed."""
        return 0

    @abstractmethod
    def fetch_price(self, ticker: str) -> Optional[float]:
        """Fetch current price for a ticker. Must be implemented by subclass."""
        pass

    def publish_price(self, ticker: str, price: float) -> None:
        """Publish price update to Redis."""
        previous = self.last_prices.get(ticker)
        change_pct = None

        if previous and previous > 0:
            change_pct = ((price - previous) / previous) * 100

        self.last_prices[ticker] = price

        event = self.producer.publish_price_update(
            ticker=ticker,
            price=price,
            source=self.name,
        )

        if event and event.event_type == EventType.PRICE_ALERT:
            log(f"ALERT: {ticker} ${price:.2f} ({change_pct:+.2f}%)")
        elif change_pct is not None and abs(change_pct) >= 0.1:
            log(f"  {ticker}: ${price:.2f} ({change_pct:+.2f}%)")

    def run(self) -> None:
        """Run the price monitoring loop."""
        tickers = self.config.tickers

        log("=" * 50)
        log(f"Price Monitor ({self.name})")
        log("=" * 50)
        log(f"Tickers: {', '.join(tickers)}")
        log(f"Interval: {self.interval} seconds")
        if self.rate_limit > 0:
            log(f"Rate limit: {self.rate_limit} seconds between calls")
        log(f"Alert threshold: {self.alert_threshold}%")
        log("")

        # Initial price fetch
        log("Fetching initial prices...")
        for i, ticker in enumerate(tickers):
            if i > 0 and self.rate_limit > 0:
                time.sleep(self.rate_limit)
            price = self.fetch_price(ticker)
            if price:
                self.last_prices[ticker] = price
                log(f"  {ticker}: ${price:,.2f}")
            else:
                log(f"  {ticker}: Failed to fetch")

        log("")
        log("Monitoring for price changes...")
        log("")

        self.running = True

        def shutdown(signum, frame):
            log("Shutting down...")
            self.running = False
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        while self.running:
            for ticker in tickers:
                if not self.running:
                    break

                price = self.fetch_price(ticker)
                if price is not None:
                    self.publish_price(ticker, price)

                if self.rate_limit > 0:
                    time.sleep(self.rate_limit)

            # Wait for next interval
            wait_time = self.interval - (len(tickers) * self.rate_limit)
            if wait_time > 0 and self.running:
                time.sleep(wait_time)

        log("Price monitor stopped")
