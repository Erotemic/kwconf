import pytest

import kwconf

click = pytest.importorskip("click")


def _ported_field_names(text):
    namespace = {}
    exec(text, namespace, namespace)
    config_cls = next(
        value
        for value in namespace.values()
        if isinstance(value, type)
        and issubclass(value, kwconf.Config)
        and value is not kwconf.Config
    )
    return list(config_cls.__default__)


def test_port_from_click_ignores_generated_help_option():
    @click.command()
    @click.option("--dataset", required=True)
    def cli(dataset):
        pass

    text = kwconf.Config.port_from_click(cli)
    assert _ported_field_names(text) == ["dataset"]


def test_port_from_click_ignores_click_85_reserved_help_name():
    class FutureHelpNameCommand(click.Command):
        """Emulate Click 8.5's reserved automatic-help storage name."""

        def get_help_option(self, ctx):
            option = super().get_help_option(ctx)
            if option is not None:
                option.name = "_click_default_help"
            return option

    @click.command(cls=FutureHelpNameCommand)
    @click.option("--dataset", required=True)
    def cli(dataset):
        pass

    text = kwconf.Config.port_from_click(cli)
    assert "_click_default_help" not in text
    assert _ported_field_names(text) == ["dataset"]


def test_port_from_click_preserves_real_help_parameter_when_auto_help_disabled():
    @click.command(add_help_option=False)
    @click.option('--help')
    def cli(help):
        pass

    text = kwconf.Config.port_from_click(cli)
    assert _ported_field_names(text) == ['help']
