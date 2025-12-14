#!/usr/bin/env python3
"""AI Trading CLI - Run trades once or on a schedule.

Usage:
    trade run                    # Run AI analysis and execute trades once
    trade run --dry-run          # Show decisions without executing
    trade run --status           # Show portfolio status
    trade schedule               # Run on schedule (default: 09:35 weekdays)
    trade schedule --test        # Test mode: run immediately once
"""

import argparse
import signal
import sys
from datetime import datetime
from pathlib import Path

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil.relativedelta import relativedelta

from src.config import load_config, TradingConfig
from src.main import run_hedge_fund
from src.brokers import create_broker, Order, OrderSide, OrderType, PositionSide
from src.tools.api import get_prices
from src.utils.ticker import to_yfinance_ticker

STATE_FILE = Path("data/broker_state.json")


def log(message: str, tz=None) -> None:
    """Log message with timestamp."""
    now = datetime.now(tz) if tz else datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {message}")


def get_latest_price(ticker: str, region: str = "us") -> float | None:
    """Get the latest price for a ticker.

    Args:
        ticker: Stock ticker symbol
        region: Market region ("us" or "japan")

    Returns:
        Latest price or None if unavailable
    """
    if region == "japan":
        return _get_price_yfinance(ticker, region)
    else:
        return _get_price_financialdatasets(ticker)


def _get_price_financialdatasets(ticker: str) -> float | None:
    """Get price from financialdatasets.ai (US stocks)."""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - relativedelta(days=7)).strftime("%Y-%m-%d")

    try:
        prices = get_prices(ticker, start_date, end_date)
        if prices:
            return prices[-1].close
    except Exception as e:
        print(f"Warning: Could not fetch price for {ticker}: {e}")
    return None


def _get_price_yfinance(ticker: str, region: str) -> float | None:
    """Get price from yfinance (US and Japan stocks)."""
    import yfinance as yf

    try:
        yf_ticker = to_yfinance_ticker(ticker, region)
        stock = yf.Ticker(yf_ticker)

        hist = stock.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])

        info = stock.fast_info
        if hasattr(info, "last_price") and info.last_price:
            return float(info.last_price)
    except Exception as e:
        print(f"Warning: Could not fetch price for {ticker}: {e}")
    return None


def is_market_holiday(date: datetime, holidays: list[str]) -> bool:
    """Check if the given date is a market holiday."""
    date_str = date.strftime("%Y-%m-%d")
    return date_str in holidays


def create_broker_from_config(config: TradingConfig):
    """Create broker instance from config."""
    return create_broker(
        initial_cash=config.broker.initial_cash,
        margin_requirement=config.broker.margin_requirement,
        slippage=config.broker.slippage,
        max_slippage=config.broker.max_slippage,
    )


def build_portfolio(broker, tickers: list[str], margin_requirement: float) -> dict:
    """Build portfolio dict for AI analysis."""
    account = broker.get_account()
    portfolio = {
        "cash": account.cash,
        "margin_requirement": margin_requirement,
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
    for ticker, pos in broker.get_positions().items():
        if ticker in portfolio["positions"]:
            if pos.side.value == "long":
                portfolio["positions"][ticker]["long"] = pos.quantity
                portfolio["positions"][ticker]["long_cost_basis"] = pos.average_cost
            else:
                portfolio["positions"][ticker]["short"] = abs(pos.quantity)
                portfolio["positions"][ticker]["short_cost_basis"] = pos.average_cost

    return portfolio


def execute_trades(broker, decisions: dict, prices: dict, log_fn=print, currency: str = "$") -> None:
    """Execute trades based on AI decisions."""
    for ticker, decision in decisions.items():
        action = decision.get("action", "hold")
        quantity = decision.get("quantity", 0)

        if action == "hold" or quantity <= 0:
            continue

        if ticker not in prices:
            continue

        order_map = {
            "buy": (OrderSide.BUY, PositionSide.LONG),
            "sell": (OrderSide.SELL, PositionSide.LONG),
            "short": (OrderSide.SELL, PositionSide.SHORT),
            "cover": (OrderSide.BUY, PositionSide.SHORT),
        }

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

        result = broker.submit_order(order)
        if result.is_filled:
            log_fn(f"  {ticker}: {action.upper()} {result.quantity_filled} @ {currency}{result.average_price:,.2f}")
        else:
            log_fn(f"  {ticker}: {result.status.value} - {result.message}")


# =============================================================================
# Subcommand: run
# =============================================================================


def cmd_run(args) -> None:
    """Run AI analysis and execute trades once."""
    config = load_config(args.config)
    region = config.market.region
    currency = config.market.currency

    # Handle --reset
    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print(f"State file deleted: {STATE_FILE}")
        else:
            print("No state file to delete")
        return

    broker = create_broker_from_config(config)

    # Load state if requested or for status
    if args.load or args.status:
        if STATE_FILE.exists():
            broker.load_state()
        elif args.status:
            print("No saved state found. Run without --status to start trading.")
            return

    # Handle --status
    if args.status:
        print("=" * 50)
        print("Portfolio Status")
        print("=" * 50)
        print()

        positions = broker.get_positions()
        if positions:
            print("--- Updating Prices ---")
            for ticker in positions.keys():
                price = get_latest_price(ticker, region)
                if price:
                    broker.set_price(ticker, price)
                    print(f"{ticker}: {currency}{price:,.2f}")
            print()

            print("--- Current Positions ---")
            for ticker, pos in broker.get_positions().items():
                side = "LONG" if pos.side.value == "long" else "SHORT"
                pnl_sign = "+" if pos.unrealized_pnl >= 0 else ""
                print(f"{ticker}: {abs(pos.quantity)} shares ({side}) @ {currency}{pos.average_cost:,.2f}")
                print(f"        Current: {currency}{pos.current_price:,.2f}  P&L: {pnl_sign}{currency}{pos.unrealized_pnl:,.2f}")
            print()

        print(broker.get_performance_summary())
        return

    # Normal run
    tickers = config.tickers
    dry_run = args.dry_run or config.consumer.dry_run

    print("=" * 50)
    print("AI Trader")
    print("=" * 50)
    print()

    account = broker.get_account()
    print(f"Cash: {currency}{account.cash:,.2f}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"Model: {config.model.name} ({config.model.provider})")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE (Mock)'}")
    print(f"State: {'Loaded' if args.load else 'Fresh'}")
    print()

    # Fetch prices
    print("--- Fetching Current Prices ---")
    prices = {}
    for ticker in tickers:
        price = get_latest_price(ticker, region)
        if price:
            prices[ticker] = price
            print(f"{ticker}: {currency}{price:,.2f}")
        else:
            print(f"{ticker}: Price not available")

    if not prices:
        print("\nError: No prices available. Check API key or network.")
        return

    broker.set_prices(prices)
    print()

    # Build portfolio and run AI
    portfolio = build_portfolio(broker, tickers, config.broker.margin_requirement)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d")

    print("--- Running AI Analysis ---")
    print("(This may take a few minutes...)")
    print()

    try:
        result = run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio=portfolio,
            show_reasoning=args.show_reasoning,
            model_name=config.model.name,
            model_provider=config.model.provider,
        )
    except Exception as e:
        print(f"\nError running AI analysis: {e}")
        return

    decisions = result.get("decisions", {})
    if not decisions:
        print("No decisions returned from AI.")
        return

    # Display decisions
    print("--- AI Decisions ---")
    for ticker, decision in decisions.items():
        action = decision.get("action", "hold")
        quantity = decision.get("quantity", 0)
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "")

        print(f"\n{ticker}:")
        print(f"  Action: {action.upper()}")
        print(f"  Quantity: {quantity}")
        print(f"  Confidence: {confidence}%")
        if reasoning:
            print(f"  Reasoning: {reasoning[:100]}...")
    print()

    # Execute trades
    if dry_run:
        print("--- Dry Run Mode: No trades executed ---")
    else:
        print("--- Executing Trades ---")
        execute_trades(broker, decisions, prices, currency=currency)
        print()

        positions = broker.get_positions()
        if positions:
            print("--- Current Positions ---")
            for ticker, pos in positions.items():
                side = "LONG" if pos.side.value == "long" else "SHORT"
                print(f"{ticker}: {abs(pos.quantity)} shares ({side}) @ {currency}{pos.average_cost:,.2f}")
            print()

    print(broker.get_performance_summary())

    # Save state
    if not args.no_save and not dry_run:
        broker.save_state()


# =============================================================================
# Subcommand: schedule
# =============================================================================


def run_scheduled_job(config: TradingConfig) -> None:
    """Execute a single scheduled trading run."""
    tz = pytz.timezone(config.market.timezone)
    now = datetime.now(tz)
    region = config.market.region
    currency = config.market.currency

    log("=" * 50, tz)
    log("Starting trading job", tz)
    log("=" * 50, tz)

    # Check market
    if now.weekday() >= 5:
        log("Market closed (weekend). Skipping.", tz)
        return
    if is_market_holiday(now, config.market.holidays):
        log("Market closed (holiday). Skipping.", tz)
        return

    broker = create_broker_from_config(config)

    if STATE_FILE.exists():
        broker.load_state()
        log("Loaded previous state", tz)
    else:
        log("Starting fresh (no previous state)", tz)

    account = broker.get_account()
    tickers = config.tickers

    log(f"Cash: {currency}{account.cash:,.2f}", tz)
    log(f"Tickers: {', '.join(tickers)}", tz)
    log(f"Model: {config.model.name}", tz)

    # Fetch prices
    log("Fetching current prices...", tz)
    prices = {}
    for ticker in tickers:
        price = get_latest_price(ticker, region)
        if price:
            prices[ticker] = price
            log(f"  {ticker}: {currency}{price:,.2f}", tz)
        else:
            log(f"  {ticker}: Price not available", tz)

    if not prices:
        log("Error: No prices available. Skipping this run.", tz)
        return

    broker.set_prices(prices)

    # Build portfolio and run AI
    portfolio = build_portfolio(broker, tickers, config.broker.margin_requirement)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d")

    log("Running AI analysis...", tz)
    try:
        result = run_hedge_fund(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date,
            portfolio=portfolio,
            show_reasoning=False,
            model_name=config.model.name,
            model_provider=config.model.provider,
        )
    except Exception as e:
        log(f"Error in AI analysis: {e}", tz)
        return

    decisions = result.get("decisions", {})
    if not decisions:
        log("No decisions from AI. Skipping.", tz)
        return

    # Display decisions
    log("AI Decisions:", tz)
    for ticker, decision in decisions.items():
        action = decision.get("action", "hold")
        quantity = decision.get("quantity", 0)
        confidence = decision.get("confidence", 0)
        log(f"  {ticker}: {action.upper()} {quantity} shares (confidence: {confidence}%)", tz)

    if config.consumer.dry_run:
        log("Dry run mode - no trades executed", tz)
    else:
        log("Executing trades...", tz)
        execute_trades(broker, decisions, prices, lambda msg: log(msg, tz), currency=currency)
        broker.save_state()

    # Summary
    log("Performance Summary:", tz)
    summary = broker.get_performance_summary()
    log(f"  Equity: {currency}{summary.current_equity:,.2f}", tz)
    log(f"  P&L: {currency}{summary.total_pnl:,.2f} ({summary.total_pnl_percent:+.2f}%)", tz)

    log("Job complete", tz)
    log("", tz)


def cmd_schedule(args) -> None:
    """Run AI trading on a schedule."""
    config = load_config(args.config)
    tz = pytz.timezone(config.market.timezone)

    # Test mode
    if args.test:
        log("Test mode - running immediately", tz)
        run_scheduled_job(config)
        return

    # Parse schedule time
    try:
        hour, minute = map(int, args.time.split(":"))
    except ValueError:
        print(f"Error: Invalid schedule format '{args.time}'. Use HH:MM")
        return

    log("=" * 50, tz)
    log("AI Trading Scheduler", tz)
    log("=" * 50, tz)
    log(f"Tickers: {', '.join(config.tickers)}", tz)
    log(f"Model: {config.model.name} ({config.model.provider})", tz)
    log(f"Schedule: {args.time} {config.market.timezone} (weekdays only)", tz)
    log(f"Dry run: {config.consumer.dry_run}", tz)
    log("", tz)
    log("Press Ctrl+C to stop", tz)
    log("", tz)

    scheduler = BlockingScheduler(timezone=tz)

    scheduler.add_job(
        run_scheduled_job,
        CronTrigger(hour=hour, minute=minute, day_of_week="mon-fri", timezone=tz),
        args=[config],
        id="trading_job",
        name="Daily Trading Job",
    )

    def shutdown(signum, frame):
        log("Shutting down scheduler...", tz)
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    next_run = scheduler.get_job("trading_job").next_run_time
    log(f"Next run: {next_run.strftime('%Y-%m-%d %H:%M:%S')} {config.market.timezone}", tz)
    log("", tz)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log("Scheduler stopped", tz)


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="AI Trading CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=str, help="Path to config file")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run AI analysis once")
    run_parser.add_argument("--show-reasoning", action="store_true", help="Show AI reasoning")
    run_parser.add_argument("--dry-run", action="store_true", help="Don't execute trades")
    run_parser.add_argument("--status", action="store_true", help="Show portfolio status")
    run_parser.add_argument("--load", action="store_true", help="Load previous state")
    run_parser.add_argument("--no-save", action="store_true", help="Don't save state after")
    run_parser.add_argument("--reset", action="store_true", help="Delete saved state")

    # schedule subcommand
    schedule_parser = subparsers.add_parser("schedule", help="Run on schedule")
    schedule_parser.add_argument("--time", type=str, default="09:35", help="Time to run (HH:MM)")
    schedule_parser.add_argument("--test", action="store_true", help="Run immediately once")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
