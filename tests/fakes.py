"""Fake API answers shared by the tests (no network)."""

import json

# Copied from a real answer (2026-11-05), shortened to 3 rows.
SAMPLE_ROWS = [
    {"date": "2026-11-05", "base": "MAD", "quote": "EUR", "rate": 0.090873},
    {"date": "2026-11-05", "base": "MAD", "quote": "MAD", "rate": 1.0},
    {"date": "2026-11-05", "base": "MAD", "quote": "USD", "rate": 0.10456},
]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.url = "https://fake.api/test"

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class FakeSession:
    """Plays a list of answers (FakeResponse or exception) in order and records calls."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
