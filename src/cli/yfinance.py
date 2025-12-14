#!/usr/bin/env python3
"""yfinance Event Producer - Price monitoring for US and Japan stocks.

Usage:
    yfinance                          # Run with config file
    yfinance --config path/to/config  # Specify config
"""

import argparse
import sys
from typing import Optional

import yfinance as yf

from src.config import load_config
from src.events import EventProducer
from src.cli.base_producer import BasePriceMonitor, log
from src.utils.ticker import to_yfinance_ticker


class YfinanceMonitor(BasePriceMonitor):
    """Price monitor using yfinance (Yahoo Finance)."""

    name = "yfinance"

    @property
    def interval(self) -> int:
        return self.config.yfinance.interval

    @property
    def alert_threshold(self) -> float:
        return self.config.yfinance.alert_threshold

    def fetch_price(self, ticker: str) -> Optional[float]:
        """Fetch price from Yahoo Finance."""
        try:
            # Convert ticker to yfinance format based on region
            yf_ticker = to_yfinance_ticker(ticker, self.config.market.region)
            stock = yf.Ticker(yf_ticker)

            # Get latest price from history
            hist = stock.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])

            # Fallback to fast_info
            info = stock.fast_info
            if hasattr(info, "last_price") and info.last_price:
                return float(info.last_price)

        except Exception as e:
            log(f"Error fetching {ticker}: {e}")
        return None

    def run(self) -> None:
        """Override run to show region info."""
        region = self.config.market.region
        log(f"Market region: {region.upper()}")

        if region == "japan":
            log("Note: Japanese tickers use .T suffix (e.g., 7203.T for Toyota)")

        super().run()


def main():
    parser = argparse.ArgumentParser(description="Price Monitor (yfinance)")
    parser.add_argument("--config", type=str, help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)

    producer = EventProducer(
        redis_url=config.redis.url,
        channel=config.redis.channel,
    )

    if not producer.health_check():
        log("ERROR: Cannot connect to Redis")
        sys.exit(1)

    log("Connected to Redis")

    monitor = YfinanceMonitor(config, producer)
    monitor.run()


if __name__ == "__main__":
    main()
