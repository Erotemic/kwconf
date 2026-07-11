import kwconf
from kwconf import _ingest
from kwconf import config as config_mod
from kwconf import subconfig as subconfig_mod


def test_flat_and_nested_loading_share_source_normalization(monkeypatch):
    calls = []

    def fake_coerce(data, mode=None):
        calls.append((data, mode))
        return {'value': 3}

    monkeypatch.setattr(_ingest, 'coerce_mapping_source', fake_coerce)

    assert config_mod._coerce_data_to_dict('source', mode='json') == {
        'value': 3
    }
    assert subconfig_mod.coerce_data_updates('source', mode='yaml') == {
        'value': 3
    }
    assert calls == [('source', 'json'), ('source', 'yaml')]


def test_config_option_bootstrap_respects_end_of_options_separator():
    assert subconfig_mod.scan_config_path(['--config=before.yaml']) == (
        'before.yaml'
    )
    assert subconfig_mod.scan_config_path(['--', '--config=after.yaml']) is None


def test_shared_argv_normalization_returns_fresh_lists():
    original = ['--value=3']
    normalized = _ingest.coerce_argv(original)
    assert normalized == original
    assert normalized is not original


def test_nested_and_flat_mapping_sources_have_matching_type_errors():
    class Demo(kwconf.Config):
        value = 1

    for loader in [
        lambda: config_mod._coerce_data_to_dict('[1, 2]'),
        lambda: subconfig_mod.coerce_data_updates('[1, 2]', cfg=Demo()),
    ]:
        try:
            loader()
        except TypeError as ex:
            assert 'did not parse to a mapping' in str(ex)
        else:  # nocover
            raise AssertionError('expected TypeError')
