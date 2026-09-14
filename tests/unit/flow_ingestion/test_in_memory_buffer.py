"""Unit tests for InMemoryBuffer adapter."""

from __future__ import annotations

from src.modules.flow_ingestion.adapters.in_memory_buffer import InMemoryBuffer


def test_in_memory_buffer_append_and_drain() -> None:
    """[US-5][AC-137] Verify circular buffer stores and drains messages FIFO."""
    buf = InMemoryBuffer(capacity=5)
    assert buf.size == 0
    assert buf.capacity == 5
    assert buf.is_empty is True

    buf.push({"msg": 1})
    buf.push({"msg": 2})
    assert buf.size == 2
    assert buf.is_empty is False

    drained = buf.drain()
    assert drained == [{"msg": 1}, {"msg": 2}]
    assert buf.size == 0
    assert buf.is_empty is True


def test_in_memory_buffer_capacity_eviction() -> None:
    """[US-5][AC-137] Verify buffer evicts oldest element when capacity is exceeded."""
    buf = InMemoryBuffer(capacity=2)
    buf.push({"id": 1})
    buf.push({"id": 2})
    buf.push({"id": 3})

    assert buf.size == 2
    drained = buf.drain()
    assert drained == [{"id": 2}, {"id": 3}]


def test_in_memory_buffer_clear() -> None:
    """[US-5][AC-137] Verify clear drops all buffered items."""
    buf = InMemoryBuffer(capacity=5)
    buf.push({"test": True})
    buf.clear()
    assert buf.size == 0
    assert buf.drain() == []
