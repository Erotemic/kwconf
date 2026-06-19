"""
Small text helpers vendored to keep kwconf dependency-free at runtime.

These reproduce the behavior of the equivalent ``ubelt`` functions (which
kwconf used to depend on); the test suite asserts they stay byte-compatible.
"""
from __future__ import annotations

import textwrap


def codeblock(text: str) -> str:
    """
    Dedent a triple-quoted block and strip surrounding blank lines.

    Equivalent to ``ubelt.codeblock``.
    """
    return textwrap.dedent(text).strip('\n')


def paragraph(text: str) -> str:
    """
    Collapse all runs of whitespace (including newlines) into single spaces.

    Equivalent to ``ubelt.paragraph``.
    """
    return ' '.join(text.split())


def indent(text: str, prefix: str = '    ') -> str:
    """
    Prefix every line (including blank lines) with ``prefix``.

    Unlike :func:`textwrap.indent`, this indents empty lines too, matching
    ``ubelt.indent``.
    """
    return prefix + text.replace('\n', '\n' + prefix)
