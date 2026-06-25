# mypy: disable-error-code="operator, arg-type, attr-defined, misc, literal-required, import-untyped, assignment, var-annotated, dict-item, list-item, call-arg"
"""
The default passed to ``kwconf.Value`` is a Python-boundary value and is stored
verbatim (WYSIWYG). It is NOT run through the coerce/auto parser. Coercion only
happens at the text boundary (argv/env/``Config.coerce``). See design.md §4.
"""

import kwconf


def test_string_default_is_not_coerced():
    v = kwconf.Value('512')
    assert v.value == '512'
    assert isinstance(v.value, str)


def test_string_default_with_parser_is_not_coerced():
    # Even an explicit parser must not touch the trusted default.
    v = kwconf.Value('512', parser='yaml')
    assert v.value == '512'
    assert isinstance(v.value, str)


def test_non_string_default_passes_through():
    assert kwconf.Value(512).value == 512
    assert kwconf.Value(None).value is None


def test_default_factory_output_is_verbatim():
    v = kwconf.Value(default_factory=lambda: '512')
    assert v.value == '512'
    assert isinstance(v.value, str)


def test_default_wysiwyg_on_config():
    class C(kwconf.Config):
        some_int: int = kwconf.Value(512)
        int_or_str: int | str = kwconf.Value('512')
        plain = kwconf.Value('512')

    c = C()
    assert c['some_int'] == 512 and isinstance(c['some_int'], int)
    assert c['int_or_str'] == '512' and isinstance(c['int_or_str'], str)
    assert c['plain'] == '512' and isinstance(c['plain'], str)


def test_text_boundary_still_coerces():
    # The default is WYSIWYG, but argv tokens are still parsed.
    class C(kwconf.Config):
        some_int: int = kwconf.Value('512')

    # Default path: verbatim string.
    assert C()['some_int'] == '512'
    # argv path: coerced to int.
    parsed = C.cli(argv=['--some_int=99'])
    assert parsed['some_int'] == 99 and isinstance(parsed['some_int'], int)


def test_cli_with_no_argv_preserves_verbatim_default():
    # argparse parses *string* defaults through the action's type=; the
    # not-given merge in _read_argv must use the verbatim kwconf default so the
    # WYSIWYG guarantee holds through .cli(), not just the plain constructor.
    class C(kwconf.Config):
        int_or_str: int | str = kwconf.Value('512')
        str_or_null: str | None = kwconf.Value(None)
        yaml_default: list = kwconf.Value('512', parser='yaml')

    cfg = C.cli(argv=[])
    assert cfg['int_or_str'] == '512' and isinstance(cfg['int_or_str'], str)
    assert cfg['str_or_null'] is None
    assert cfg['yaml_default'] == '512' and isinstance(cfg['yaml_default'], str)
