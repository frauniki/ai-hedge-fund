"""Event consumer for processing trading events from Redis."""

import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import redis

from .models import EventType, TradingEvent


class EventConsumer:
    """Consumes trading events from Redis and processes them.

    Supports registering handlers for different event types.

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
        self._pubsub = self._redis.pubsub()
        self._channel = channel
        self._handlers: Dict[EventType, List[Callable[[TradingEvent], None]]] = {}
        self._running = False
        self._default_handler: Optional[Callable[[TradingEvent], None]] = None

    def register_handler(
        self,
        event_type: EventType,
        handler: Callable[[TradingEvent], None],
    ) -> None:
        """Register a handler for a specific event type.

        Args:
            event_type: Type of event to handle
            handler: Function to call when event is received
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def set_default_handler(
        self,
        handler: Callable[[TradingEvent], None],
    ) -> None:
        """Set a default handler for all events.

        Args:
            handler: Function to call for any event without specific handler
        """
        self._default_handler = handler

    def _process_event(self, event: TradingEvent) -> None:
        """Process a single event by calling registered handlers.

        Args:
            event: The event to process
        """
        handlers = self._handlers.get(event.event_type, [])

        if handlers:
            for handler in handlers:
                try:
                    handler(event)
                except Exception as e:
                    self._log(f"Error in handler for {event.event_type}: {e}")
        elif self._default_handler:
            try:
                self._default_handler(event)
            except Exception as e:
                self._log(f"Error in default handler: {e}")
        else:
            self._log(f"No handler for event type: {event.event_type}")

    def _log(self, message: str) -> None:
        """Log a message with timestamp."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] {message}")

    def start(self, blocking: bool = True) -> None:
        """Start consuming events.

        Args:
            blocking: If True, blocks until stop() is called
        """
        self._pubsub.subscribe(self._channel)
        self._running = True
        self._log(f"Subscribed to channel: {self._channel}")

        # Setup graceful shutdown
        def shutdown(signum, frame):
            self._log("Shutting down consumer...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        if blocking:
            self._consume_loop()

    def _consume_loop(self) -> None:
        """Main event consumption loop."""
        self._log("Consumer started, waiting for events...")

        for message in self._pubsub.listen():
            if not self._running:
                break

            if message["type"] != "message":
                continue

            try:
                event = TradingEvent.from_json(message["data"])
                self._log(f"Received: {event}")
                self._process_event(event)
            except Exception as e:
                self._log(f"Error processing message: {e}")

    def stop(self) -> None:
        """Stop consuming events."""
        self._running = False
        self._pubsub.unsubscribe()
        self._log("Consumer stopped")

    def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            return self._redis.ping()
        except redis.ConnectionError:
            return False
