"""
Test that we can play very nicely with argparse
"""
import argparse
from pathlib import Path


def setup_args1():
    parser = argparse.ArgumentParser(
        description="Description 1",
    )

    # Configuration
    parser.add_argument(
        "--config", "-c",
        type=Path,
        help="Path to configuration YAML file"
    )

    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        help="Output directory"
    )
    return parser


def setup_args2():
    parser = argparse.ArgumentParser(
        description="Description 2",
    )

    # Input data
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing the input"
    )

    parser.add_argument(
        "--option",
        type=str,
        choices=['value1', 'value2'],
        help="Some option",
    )
    return parser


def main1():
    parser = setup_args1()
    args = parser.parse_args()
    print(f'args={args}')


def main2():
    parser = setup_args2()
    args = parser.parse_args()
    print(f'args={args}')


def build_modal():
    from kwconf.modal import ModalCLI
    modal = ModalCLI()

    import kwconf
    # FIXME: doesn't work when you use Config instead of DataConfig.
    cli1 = kwconf.DataConfig.cls_from_argparse(setup_args1(), name="mode1")
    cli1.main = main2

    cli2 = kwconf.DataConfig.cls_from_argparse(setup_args2(), name="mode2")
    cli2.main = main2

    modal.register(cli1)
    modal.register(cli2)
    return modal


def test_argparse_playnice():
    """
    """
    modal = build_modal()
    parser = modal.argparse()
    parser.print_usage()


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/kwconf/tests/test_argparse_integration.py
    """
    build_modal().main()
