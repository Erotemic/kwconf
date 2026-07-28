"""
Tests for Value(required=True) enforcement.
"""

import pytest

import kwconf


class ReqConfig(kwconf.Config):
    k = kwconf.Value(0, required=True)
    other = kwconf.Value('x')


def test_required_missing_raises():
    with pytest.raises(ValueError, match='Required'):
        ReqConfig.cli(argv=[])
    with pytest.raises(ValueError, match='Required'):
        ReqConfig.cli(data={'other': 'y'}, argv=False)


def test_required_satisfied_by_explicit_default_on_argv():
    """Explicitly passing the default value must satisfy the requirement."""
    cfg = ReqConfig.cli(argv=['--k=0'])
    assert cfg['k'] == 0


def test_required_satisfied_by_explicit_default_in_data():
    cfg = ReqConfig.cli(data={'k': 0}, argv=False)
    assert cfg['k'] == 0


def test_required_satisfied_by_non_default_value():
    cfg = ReqConfig.cli(argv=['--k=5'])
    assert cfg['k'] == 5
