"""In-memory circular buffer adapter for offline fallback telemetry storage."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any


class InMemoryBuffer:
    """Thread-safe FIFO circular buffer with fixed capacity."""

    def __init__(self, capacity: int = 1000) -> None:
        """Initializes buffer with a maximum capacity.

        Args:
            capacity: Maximum number of payloads to retain before evicting oldest.
        """
        self._capacity = capacity
        self._deque: deque[Mapping[str, Any]] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        """Returns the maximum buffer capacity."""
        return self._capacity

    @property
    def size(self) -> int:
        """Returns the current number of buffered items."""
        return len(self._deque)

    @property
    def is_empty(self) -> bool:
        """Returns True if buffer has no items."""
        return len(self._deque) == 0

    def push(self, item: Mapping[str, Any]) -> None:
        """Appends an item to the buffer, evicting the oldest if full.

        Args:
            item: Telemetry payload mapping.
        """
        self._deque.append(dict(item))

    def drain(self) -> list[Mapping[str, Any]]:
        """Removes and returns all buffered items in FIFO order.

        Returns:
            List of all previously buffered payload dictionaries.
        """
        items: list[Mapping[str, Any]] = list(self._deque)
        self._deque.clear()
        return items

    def clear(self) -> None:
        """Discards all buffered items."""
        self._deque.clear()
