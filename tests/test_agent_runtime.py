import threading

from app.agent import runtime


def test_register_get_unregister():
    ctx = runtime.register("t1")
    assert runtime.get("t1") is ctx
    assert isinstance(ctx.cancel_event, threading.Event)
    assert not ctx.cancel_event.is_set()

    runtime.unregister("t1")
    assert runtime.get("t1") is None


def test_register_replaces_previous_context():
    first = runtime.register("t1")
    second = runtime.register("t1")
    assert runtime.get("t1") is second
    assert first is not second
    runtime.unregister("t1")


def test_request_cancel_sets_event():
    ctx = runtime.register("t1")
    assert runtime.request_cancel("t1") is True
    assert ctx.cancel_event.is_set()
    runtime.unregister("t1")


def test_request_cancel_without_context_returns_false():
    assert runtime.request_cancel("missing") is False
    assert runtime.request_cancel(None) is False
