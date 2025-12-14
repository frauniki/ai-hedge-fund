#!/usr/bin/env python3
"""Event Consumer - Processes trading events and executes trades.

Usage:
    consume                          # Run with config file
    consume --config path/to/config  # Specify config
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta

from src.config import load_config, TradingConfig
from src.events import EventConsumer, EventType, TradingEvent
from src.main import run_hedge_fund
from src.brokers import create_broker, Order, OrderSide, OrderType, PositionSide

STATE_FILE = Path("data/broker_state.json")


def log(message: str) -> None:
    """Log message with timestamp."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}")


def get_latest_price(ticker: str) -> float | None:
    """Get the latest price for a ticker."""
    from src.tools.api import get_prices

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - relativedelta(days=7)).strftime("%Y-%m-%d")

    try:
        prices = get_prices(ticker, start_date, end_date)
        if prices:
            return prices[-1].close
    except Exception as e:
        log(f"Warning: Could not fetch price for {ticker}: {e}")
    return None


class TradingEventHandler:
    """Handles trading events by running AI analysis and executing trades."""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.broker = create_broker(
            initial_cash=config.broker.initial_cash,
            margin_requirement=config.broker.margin_requirement,
            slippage=config.broker.slippage,
            max_slippage=config.broker.max_slippage,
        )

        if STATE_FILE.exists():
            self.broker.load_state()
            log("Loaded broker state")

    def handle_price_alert(self, event: TradingEvent) -> None:
        """Handle significant price movement events."""
        ticker = event.ticker
        if not ticker:
            log("Price alert without ticker, skipping")
            return

        data = event.data
        price = data.get("price")
        change_pct = data.get("change_percent", 0)

        log("=" * 50)
        log(f"PRICE ALERT: {ticker}")
        log(f"  Price: ${price:,.2f}" if price else "  Price: N/A")
        log(f"  Change: {change_pct:+.2f}%")
        log("=" * 50)

        self._run_analysis([ticker])

    def handle_scheduled(self, event: TradingEvent) -> None:
        """Handle scheduled analysis events."""
        tickers = event.data.get("tickers", [])
        if not tickers:
            tickers = self.config.tickers

        log("=" * 50)
        log("SCHEDULED ANALYSIS")
        log(f"  Tickers: {', '.join(tickers)}")
        log("=" * 50)

        self._run_analysis(tickers)

    def handle_trade_signal(self, event: TradingEvent) -> None:
        """Handle external trade signals."""
        ticker = event.ticker
        if not ticker:
            return

        data = event.data
        signal = data.get("signal")
        confidence = data.get("confidence", 0)

        log("=" * 50)
        log(f"TRADE SIGNAL: {ticker}")
        log(f"  Signal: {signal}")
        log(f"  Confidence: {confidence}%")
        log(f"  Source: {event.source}")
        log("=" * 50)

        if confidence >= self.config.consumer.min_confidence:
            self._run_analysis([ticker])
        else:
            log(f"Confidence too low ({confidence}%), skipping")

    def _run_analysis(self, tickers: list[str]) -> None:
        """Run AI analysis and execute trades."""
        log(f"Running AI analysis for: {', '.join(tickers)}")

        # Fetch prices
        prices = {}
        for ticker in tickers:
            price = get_latest_price(ticker)
            if price:
                prices[ticker] = price
                log(f"  {ticker}: ${price:,.2f}")
            else:
                log(f"  {ticker}: Price unavailable")

        if not prices:
            log("No prices available, skipping analysis")
            return

        self.broker.set_prices(prices)

        # Build portfolio
        account = self.broker.get_account()
        portfolio = {
            "cash": account.cash,
            "margin_requirement": self.config.broker.margin_requirement,
            "margin_used": 0.0,
            "positions": {
                ticker: {
                    "long": 0,
                    "short": 0,
                    "long_cost_basis": 0.0,
                    "short_cost_basis": 0.0,
                    "short_margin_used": 0.0,
                }
                for ticker in tickers
            },
            "realized_gains": {ticker: {"long": 0.0, "short": 0.0} for ticker in tickers},
        }

        # Add existing positions
        for ticker, pos in self.broker.get_positions().items():
            if ticker in portfolio["positions"]:
                if pos.side.value == "long":
                    portfolio["positions"][ticker]["long"] = pos.quantity
                    portfolio["positions"][ticker]["long_cost_basis"] = pos.average_cost
                else:
                    portfolio["positions"][ticker]["short"] = abs(pos.quantity)
                    portfolio["positions"][ticker]["short_cost_basis"] = pos.average_cost

        # Run AI
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d")

        try:
            result = run_hedge_fund(
                tickers=tickers,
                start_date=start_date,
                end_date=end_date,
                portfolio=portfolio,
                show_reasoning=False,
                model_name=self.config.model.name,
                model_provider=self.config.model.provider,
            )
        except Exception as e:
            log(f"Error in AI analysis: {e}")
            return

        decisions = result.get("decisions", {})
        if not decisions:
            log("No decisions from AI")
            return

        # Display and execute
        log("AI Decisions:")
        for ticker, decision in decisions.items():
            action = decision.get("action", "hold")
            quantity = decision.get("quantity", 0)
            confidence = decision.get("confidence", 0)
            log(f"  {ticker}: {action.upper()} {quantity} (confidence: {confidence}%)")

        if self.config.consumer.dry_run:
            log("Dry run - no trades executed")
        else:
            self._execute_trades(decisions, prices)

        # Show summary
        summary = self.broker.get_performance_summary()
        log(f"Equity: ${summary.current_equity:,.2f}, P&L: {summary.total_pnl_percent:+.2f}%")

    def _execute_trades(self, decisions: dict, prices: dict) -> None:
        """Execute trades based on AI decisions."""
        log("Executing trades...")

        order_map = {
            "buy": (OrderSide.BUY, PositionSide.LONG),
            "sell": (OrderSide.SELL, PositionSide.LONG),
            "short": (OrderSide.SELL, PositionSide.SHORT),
            "cover": (OrderSide.BUY, PositionSide.SHORT),
        }

        for ticker, decision in decisions.items():
            action = decision.get("action", "hold")
            quantity = decision.get("quantity", 0)

            if action == "hold" or quantity <= 0:
                continue

            if ticker not in prices:
                continue

            if action not in order_map:
                continue

            side, position_side = order_map[action]
            order = Order(
                ticker=ticker,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET,
                position_side=position_side,
            )

            result = self.broker.submit_order(order)
            if result.is_filled:
                log(f"  {ticker}: {action.upper()} {result.quantity_filled} @ ${result.average_price:,.2f}")
            else:
                log(f"  {ticker}: {result.status.value} - {result.message}")

        self.broker.save_state()


def main():
    parser = argparse.ArgumentParser(description="Trading Event Consumer")
    parser.add_argument("--config", type=str, help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)
    handler = TradingEventHandler(config)

    consumer = EventConsumer(
        redis_url=config.redis.url,
        channel=config.redis.channel,
    )

    consumer.register_handler(EventType.PRICE_ALERT, handler.handle_price_alert)
    consumer.register_handler(EventType.SCHEDULED, handler.handle_scheduled)
    consumer.register_handler(EventType.TRADE_SIGNAL, handler.handle_trade_signal)

    if not consumer.health_check():
        log("ERROR: Cannot connect to Redis")
        sys.exit(1)

    log("Connected to Redis")
    log(f"Model: {config.model.name} ({config.model.provider})")
    log(f"Dry run: {config.consumer.dry_run}")
    log("")

    consumer.start(blocking=True)


if __name__ == "__main__":
    main()
