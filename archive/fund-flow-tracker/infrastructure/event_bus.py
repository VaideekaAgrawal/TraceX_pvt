"""
In-process event bus — topic-based pub/sub that mirrors Kafka semantics.

In production, swap this for confluent-kafka-python with zero service code changes.
Each service subscribes to topics and publishes events; the bus routes messages.
"""
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from queue import Queue, Empty

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Single event on the bus."""
    topic: str
    payload: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_service: str = ""
    event_id: str = ""
    _offset: int = 0


class DeadLetterQueue:
    """Stores events that failed processing — monitored, not discarded."""

    def __init__(self, max_size: int = 10_000):
        self._lock = threading.Lock()
        self._items: deque = deque(maxlen=max_size)
        self._max_size = max_size

    def push(self, event: Event, error: str, consumer: str):
        with self._lock:
            self._items.append({
                "event": event,
                "error": error,
                "consumer": consumer,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.warning(
                "DLQ: event %s from topic '%s' failed in %s: %s",
                event.event_id, event.topic, consumer, error,
            )

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._items)

    def drain(self, limit: int = 100) -> List[Dict]:
        with self._lock:
            items = list(self._items)[:limit]
            for _ in range(min(limit, len(self._items))):
                self._items.popleft()
            return items

    def peek(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            return list(self._items)[:limit]


class EventBus:
    """
    In-process event bus with topic-based routing.

    Mirrors Kafka semantics:
    - Topics are ordered logs
    - Consumers subscribe to topics with a callback
    - Failed events go to a dead-letter queue
    - Offset tracking per consumer group
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._event_log: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10_000))
        self._offsets: Dict[str, int] = defaultdict(int)
        self._dlq = DeadLetterQueue()
        self._counter = 0

    @property
    def dlq(self) -> DeadLetterQueue:
        return self._dlq

    def publish(self, topic: str, payload: Any, source_service: str = ""):
        """Publish an event to a topic. All subscribers are notified synchronously."""
        with self._lock:
            self._counter += 1
            event = Event(
                topic=topic,
                payload=payload,
                source_service=source_service,
                event_id=f"evt-{self._counter:08d}",
                _offset=self._counter,
            )
            self._event_log[topic].append(event)

        # Deliver to subscribers outside the lock
        for callback in self._subscribers.get(topic, []):
            try:
                callback(event)
            except Exception as exc:
                self._dlq.push(event, str(exc), callback.__qualname__)

    def subscribe(self, topic: str, callback: Callable[[Event], None]):
        """Register a callback for a topic."""
        with self._lock:
            self._subscribers[topic].append(callback)
            logger.info("Subscribed %s to topic '%s'", callback.__qualname__, topic)

    def get_topic_depth(self, topic: str) -> int:
        """Number of events published to a topic."""
        with self._lock:
            return len(self._event_log.get(topic, []))

    def get_stats(self) -> Dict[str, Any]:
        """Bus-level statistics for health monitoring."""
        with self._lock:
            return {
                "total_events": self._counter,
                "topics": {t: len(events) for t, events in self._event_log.items()},
                "subscriber_counts": {t: len(subs) for t, subs in self._subscribers.items()},
                "dlq_depth": self._dlq.depth,
            }


# Module-level singleton — import and use directly
bus = EventBus()


# ── Topic constants ────────────────────────────────────────────────────────
class Topics:
    """Canonical topic names used across services."""
    RAW_TRANSACTIONS = "raw.transactions"
    NORMALISED_TRANSACTIONS = "normalised.transactions"
    GRAPH_UPDATED = "graph.updated"
    DETECTION_RESULT = "detection.result"
    ALERT_CREATED = "alert.created"
    CASE_UPDATED = "case.updated"
    HEALTH_PING = "health.ping"
    HEALTH_PONG = "health.pong"
    REALTIME_TRANSACTION = "realtime.transaction"
    REALTIME_ALERT = "realtime.alert"
    REALTIME_DONE = "realtime.done"
