"""Tiny thread-safe pub/sub event bus.

Lets plugins decouple from each other: a producer publishes a topic payload,
any number of subscribers receive it. Subscriber callbacks run synchronously
on the publisher's thread, so they must be cheap / non-blocking — offload
real work to the subscriber's own thread.

Topics are dotted strings by convention, e.g. `headset.battery`, `cs2.state`.
"""
import logging
import threading


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs = {}          # topic -> list[callable]
        self._last = {}          # topic -> last payload (for late subscribers)

    def subscribe(self, topic, callback, replay_last=True):
        """Register `callback(payload)` for `topic`. If `replay_last` and a
        payload was already published on this topic, the callback is invoked
        immediately with it (so late-starting plugins aren't blind)."""
        with self._lock:
            self._subs.setdefault(topic, []).append(callback)
            last = self._last.get(topic, _UNSET)
        if replay_last and last is not _UNSET:
            self._safe_call(callback, last)

    def unsubscribe(self, topic, callback):
        with self._lock:
            if topic in self._subs and callback in self._subs[topic]:
                self._subs[topic].remove(callback)

    def publish(self, topic, payload):
        with self._lock:
            self._last[topic] = payload
            callbacks = list(self._subs.get(topic, ()))
        for cb in callbacks:
            self._safe_call(cb, payload)

    def latest(self, topic, default=None):
        with self._lock:
            return self._last.get(topic, default)

    @staticmethod
    def _safe_call(cb, payload):
        try:
            cb(payload)
        except Exception:
            logging.exception("[events] subscriber callback failed")


_UNSET = object()
