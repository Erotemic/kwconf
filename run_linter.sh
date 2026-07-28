#!/usr/bin/env bash
# Syntax-level gate (keeps parity with the historical flake8 check) ...
flake8 --count --select=E9,F63,F7,F82 --show-source --statistics kwconf
flake8 --count --select=E9,F63,F7,F82 --show-source --statistics ./tests
# ... plus the project's configured ruff rules (see [tool.ruff] in
# pyproject.toml) and the ruff formatter, which are the primary style gate.
ruff check kwconf tests
ruff format --check kwconf tests
