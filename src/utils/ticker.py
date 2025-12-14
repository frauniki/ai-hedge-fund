"""Ticker symbol utilities for different markets."""

from typing import List


def normalize_ticker(ticker: str, region: str = "us") -> str:
    """Normalize ticker symbol for the given region.

    Args:
        ticker: Raw ticker symbol (e.g., "7203", "7203.T", "AAPL")
        region: Market region ("us" or "japan")

    Returns:
        Normalized ticker for the data source
    """
    ticker = ticker.strip().upper()

    if region == "japan":
        # Remove .T suffix if present, then add it back
        ticker = ticker.replace(".T", "")
        # Japanese tickers are typically 4-digit numbers
        if ticker.isdigit():
            return f"{ticker}.T"
        # Could be index like "N225" or other
        return ticker
    else:
        # US tickers - remove any suffix
        return ticker.split(".")[0]


def to_yfinance_ticker(ticker: str, region: str = "us") -> str:
    """Convert ticker to yfinance format.

    Args:
        ticker: Ticker symbol
        region: Market region

    Returns:
        yfinance-compatible ticker
    """
    if region == "japan":
        ticker = ticker.replace(".T", "")
        if ticker.isdigit():
            return f"{ticker}.T"
        return ticker
    return ticker


def from_yfinance_ticker(ticker: str, region: str = "us") -> str:
    """Convert yfinance ticker back to display format.

    Args:
        ticker: yfinance ticker
        region: Market region

    Returns:
        Display-friendly ticker
    """
    if region == "japan":
        return ticker.replace(".T", "")
    return ticker


def normalize_tickers(tickers: List[str], region: str = "us") -> List[str]:
    """Normalize a list of tickers.

    Args:
        tickers: List of ticker symbols
        region: Market region

    Returns:
        List of normalized tickers
    """
    return [normalize_ticker(t, region) for t in tickers]


def get_ticker_info(ticker: str) -> dict:
    """Get information about a ticker's market.

    Args:
        ticker: Ticker symbol

    Returns:
        Dict with market info
    """
    ticker = ticker.upper()

    # Check suffix
    if ticker.endswith(".T"):
        return {"region": "japan", "exchange": "TSE", "suffix": ".T"}
    elif ticker.endswith(".L"):
        return {"region": "uk", "exchange": "LSE", "suffix": ".L"}
    elif ticker.endswith(".HK"):
        return {"region": "hongkong", "exchange": "HKEX", "suffix": ".HK"}

    # Check if numeric (likely Japanese)
    base = ticker.split(".")[0]
    if base.isdigit() and len(base) == 4:
        return {"region": "japan", "exchange": "TSE", "suffix": ".T"}

    # Default to US
    return {"region": "us", "exchange": "NYSE/NASDAQ", "suffix": ""}
