#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A library module that opens with a shebang and a PEP-263 coding line.

ADVERSARIAL SHAPE: a top-of-file inserter (``__all__`` / ``from typing import
final`` / ``from __future__ import annotations``) must keep the shebang on
physical line 1 and the coding line on line 2 (the ``_prologue_length`` /
``_safe_insertion_index`` fix). If an objective lands anything, line 1 must still
start ``#!`` and the result must re-parse; otherwise it must refuse.
"""


def public_one():
    return 1


def public_two():
    return 2
