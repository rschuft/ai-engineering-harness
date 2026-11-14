"""Shared test support for the native profile (plan leaf E-05.9): synthetic native tokens, built at run time so that
no token-shaped literal lands in the repository, and an observed in-memory credential provider."""
from __future__ import annotations

import base64
import hashlib

PREFIX = 'sk-ant-' + 'oat01' + '-'      # the public part of a synthetic token (the grammar's label is not narrowed)


def token(seed: str = 'E-05.9 synthetic native token', length: int = 99) -> str:
    """A synthetic token of the native shape: PREFIX and the URL-safe base64 of a seed's sha512, LENGTH in all."""
    body = base64.urlsafe_b64encode(hashlib.sha512(seed.encode('utf-8')).digest()).decode('ascii').rstrip('=')
    while len(PREFIX) + len(body) < length:
        body += base64.urlsafe_b64encode(hashlib.sha512(body.encode('ascii')).digest()).decode('ascii').rstrip('=')
    return (PREFIX + body)[:length]


class ObservedProvider:
    """An in-memory credential provider whose every call is recorded (``reads``: the entry names read); it refuses
    to be written, so a test sees that the dispatcher only reads."""
    name = 'memory-observed'

    def __init__(self, entries=None, error=None):
        self.entries, self.error, self.reads = dict(entries or {}), error, []

    def get(self, name):
        self.reads.append(name)
        if self.error is not None:
            raise self.error
        return self.entries.get(name)

    def set(self, *args, **kwargs):
        raise AssertionError('the dispatcher wrote a credential entry')

    def delete(self, *args, **kwargs):
        raise AssertionError('the dispatcher deleted a credential entry')
