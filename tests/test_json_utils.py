"""pretty_json: stable two-space indentation, no ASCII escaping."""

from __future__ import annotations

import json

from app.utils.json_utils import pretty_json


def test_pretty_json_indents_and_round_trips():
    data = {"b": [1, 2], "a": {"nested": True}}
    text = pretty_json(data)
    assert '\n  "b": [' in text          # two-space indent, insertion order kept
    assert json.loads(text) == data


def test_pretty_json_keeps_unicode_readable():
    # ensure_ascii=False is the whole point: Turkish text stays human-readable.
    text = pretty_json({"mesaj": "başmühendis çağrısı"})
    assert "başmühendis çağrısı" in text
    assert "\\u" not in text
