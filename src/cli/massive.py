#!/usr/bin/env python3
"""Massive.com Event Producer - Real-time/delayed price monitoring.

Usage:
    massive                          # Run with config (mode from config)
    massive --config path/to/config  # Specify config
    massive --mode websocket         # Override mode (requires paid plan)
"""

import argparse
import os
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from massive import RESTClient
from massive.websocket import WebSocketClient

from src.config import load_config
from src.events import EventProducer
from src.cli.base_producer import BasePriceMonitor, log


class MassiveMonitor(BasePriceMonitor):
    """Price monitor using Massive.com API."""

    name = "massive"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.api_key = os.getenv("MASSIVE_API_KEY")
        if not self.api_key:
            raise ValueError("MASSIVE_API_KEY must be set in .env\n" "Get your free API key at https://massive.com/")

        self.client = RESTClient(self.api_key)

    @property
    def interval(self) -> int:
        return self.config.massive.interval

    @property
    def alert_threshold(self) -> float:
        return self.config.massive.alert_threshold

    @property
    def rate_limit(self) -> int:
        return self.config.massive.rate_limit

    def fetch_price(self, ticker: str) -> Optional[float]:
        """Fetch price from Massive.com REST API."""
        try:
            aggs = self.client.get_previous_close_agg(ticker)
            if aggs and len(aggs) > 0:
                return float(aggs[0].close)
        except Exception as e:
            log(f"Error fetching {ticker}: {e}")
        return None

    def run_websocket(self) -> None:
        """Run WebSocket-based price monitoring (paid tier)."""
        tickers = self.config.tickers

        log("=" * 50)
        log("Massive.com Price Monitor (WebSocket Mode)")
        log("=" * 50)
        log(f"Tickers: {', '.join(tickers)}")
        log(f"Alert threshold: {self.alert_threshold}%")
        log("")
        log("Note: WebSocket requires paid Massive.com plan")
        log("")

        self.running = True

        def handle_msg(msgs):
            for msg in msgs:
                if hasattr(msg, "symbol") and hasattr(msg, "price"):
                    ticker = msg.symbol
                    price = float(msg.price)
                    self.publish_price(ticker, price)

        try:
            ws_client = WebSocketClient(
                api_key=self.api_key,
                subscriptions=[f"T.{t}" for t in tickers],
            )

            log("Connecting to WebSocket...")
            ws_client.run(handle_msg=handle_msg)
        except Exception as e:
            log(f"WebSocket error: {e}")
            log("WebSocket may require a paid Massive.com plan")
            log("Falling back to polling mode...")
            self.run()


def main():
    parser = argparse.ArgumentParser(description="Massive.com Price Monitor")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["polling", "websocket"],
        help="Override mode from config",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    mode = args.mode or config.massive.mode

    producer = EventProducer(
        redis_url=config.redis.url,
        channel=config.redis.channel,
    )

    if not producer.health_check():
        log("ERROR: Cannot connect to Redis")
        sys.exit(1)

    log("Connected to Redis")

    try:
        monitor = MassiveMonitor(config, producer)

        if mode == "websocket":
            monitor.run_websocket()
        else:
            monitor.run()

    except ValueError as e:
        log(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
