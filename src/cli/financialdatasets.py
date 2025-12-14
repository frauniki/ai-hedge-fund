#!/usr/bin/env python3
"""financialdatasets.ai Event Producer.

Usage:
    financialdatasets                          # Run with config file
    financialdatasets --config path/to/config  # Specify config
"""

import argparse
import sys
from typing import Optional

from dateutil.relativedelta import relativedelta
from datetime import datetime

from src.config import load_config
from src.events import EventProducer
from src.tools.api import get_prices
from src.cli.base_producer import BasePriceMonitor, log


class FinancialdatasetsMonitor(BasePriceMonitor):
    """Price monitor using financialdatasets.ai API."""

    name = "financialdatasets"

    @property
    def interval(self) -> int:
        return self.config.producer.interval

    @property
    def alert_threshold(self) -> float:
        return self.config.producer.alert_threshold

    def fetch_price(self, ticker: str) -> Optional[float]:
        """Fetch price from financialdatasets.ai."""
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - relativedelta(days=7)).strftime("%Y-%m-%d")

        try:
            prices = get_prices(ticker, start_date, end_date)
            if prices:
                return prices[-1].close
        except Exception as e:
            log(f"Warning: Could not fetch price for {ticker}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Price Monitor (financialdatasets)")
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

    monitor = FinancialdatasetsMonitor(config, producer)
    monitor.run()


if __name__ == "__main__":
    main()
