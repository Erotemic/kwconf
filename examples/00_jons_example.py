r"""
Minimal kwconf usage.

This is the shape to copy into a small script: declare a Config subclass,
parse it with `.cli(...)`, and then pass the resulting object into your real
function. The output prints each resolved field as a colorized
``name : type = value`` row, then shows the plain application plan that would
be handed to real work.

DEMO:
    Command::

        python examples/00_jons_example.py --showall

        # The new auto behavior is similar to scriptconfig but more sensible
        # and if you use type annotations you get validation warnings by default, but
        # these can be disabled or turned into errors.
        python examples/00_jons_example.py --int_1=123

        # Something type annotated as an int that cannot be coerced to it will remain a string, but it will warn
        python examples/00_jons_example.py --int_1=not-an-int

        # String args are pretty normal
        python examples/00_jons_example.py --str_1=is-a-string

        # Unlike scriptconfig this is parsed as a string because auto respects its type annotation.
        python examples/00_jons_example.py --str_1=123

        # Its kind of odd to default an int | str field to a string that is confused as an int
        # but this does put you into a case where argv cannot recover the default, so try not to do this.
        # Or just use the YAML parser, so it is always explicit.
        python examples/00_jons_example.py --showall | grep int_or_str_2
        python examples/00_jons_example.py --int_or_str_2 "512"


        python examples/00_jons_example.py --int_or_str_1 None
        python examples/00_jons_example.py --str_or_null_1 None


        python examples/00_jons_example.py --float_or_null None
        python examples/00_jons_example.py --float_or_null null
        python examples/00_jons_example.py --float_or_null 1.3
        python examples/00_jons_example.py --float_or_null nan
        python examples/00_jons_example.py --float_or_null="-inf"


        # Unlike scriptconfig you don't get autosplit for free, you have to
        # use nargs or specify some kind of parser
        python examples/00_jons_example.py --tags_auto_any 1,2,3

        # Specifying a list does not change the "auto" parsing, but it does give you a warning
        python examples/00_jons_example.py --tags_auto_list 1,2,3

        # Use the parser="csv" to get something similar to old scriptconfig behavior
        python examples/00_jons_example.py --tags_csv_any 1,2,3
        python examples/00_jons_example.py --tags_csv_any 1,2,3o

        # The parser="csv" is annotation aware, so if you specify your type as list[str], it respects it and modifies behavior
        python examples/00_jons_example.py --tags_csv_str 1,2,3o

        # Using csv with list[str|bool] is weird, but its kinda makes sense
        python examples/00_jons_example.py --tags_csv_str_or_bool 1,2,true,False,0,-1,3o

        # And using `list[str|int|bool]` gives you what you would actually expect for this case
        python examples/00_jons_example.py --tags_csv_str_or_bool_or_int 1,2,true,False,0,-1,3o
        python examples/00_jons_example.py --tags_csv_str_or_bool_or_int 1,2,true,False,0,-1,3o

        # Which can also be achived by list[Any], but specfying the innner type can warn if you pass a float
        python examples/00_jons_example.py --tags_csv_any 1,2,true,False,0,-1,3o


        # YAML will not modify behavior based on type annotations, but it will warn
        python examples/00_jons_example.py --tags_yaml_list "it-can-just-be-a-string"

        # Using the YAML parser will be the most robust way to get flexible input types.
        python examples/00_jons_example.py --tags_yaml "[1,2,3]"

        # This correctly does not give a warning, no types are specified, just parse yaml normally.
        python examples/00_jons_example.py --tags_yaml_any "it-can-just-be-a-string"
        python examples/00_jons_example.py --tags_yaml_any "[1,2,3o]"

        # Weird cases
        python examples/00_jons_example.py --tags_csv_nargs
        python examples/00_jons_example.py --tags_csv_nargs "1,2,3" "4,5,6"
        python examples/00_jons_example.py --tags_csv_nargs="1,2,3"

        python examples/00_jons_example.py --tags_yaml_nargs "[1,2,3]" "[4,5,6]"
        python examples/00_jons_example.py --tags_yaml_nargs="[1,2,3]"

"""

import _bootstrap  # noqa: F401
from _bootstrap import print_resolved_config, print_rule, rich_print
import kwconf


class JonsConfig(kwconf.Config):
    """Options for a tiny image-resize command."""

    __validate__ = 'warn'

    int_1: int = kwconf.Value(512)
    str_1: str = kwconf.Value('value')
    float_1: float = kwconf.Value(0.0)

    float_or_null: float | None = kwconf.Value(None)

    # Union types modify the default value, but order does not matter.
    str_or_null_1: str | None = kwconf.Value('Some')
    int_or_str_1: int | str = kwconf.Value(512)
    int_or_str_2: int | str = kwconf.Value('512')

    # Lists parsing is fundamentally different than it was in scriptconfig. Hopfully better.
    tags_auto_any = kwconf.Value([], help='free-form labels')
    tags_auto_list: list = kwconf.Value([], help='free-form labels')

    tags_csv_any: list = kwconf.Value(
        default_factory=list,
        parser='csv',
        help='similar to old scriptconfig behavior',
    )
    # The CSV parser respects the type annotation
    tags_csv_str: list[str] = kwconf.Value(default_factory=list, parser='csv')
    tags_csv_str_or_bool: list[str | bool] = kwconf.Value(
        default_factory=list, parser='csv'
    )
    tags_csv_str_or_bool_or_int: list[str | bool | int] = kwconf.Value(
        default_factory=list, parser='csv'
    )

    tags_csv_nargs = kwconf.Value(default_factory=list, parser='csv', nargs='*')

    # YAML never changes parsing based on the type annotations, but it does warn if the YAML types do not agree
    tags_yaml_list: list = kwconf.Value(
        default_factory=list, parser='yaml', help='free-form labels'
    )
    tags_yaml_any = kwconf.Value(None, parser='yaml', help='free-form labels')

    tags_yaml_nargs = kwconf.Value(None, parser='yaml', nargs='+')

    tags_nargs: list = kwconf.Value(
        default_factory=list, nargs='+', help='free-form labels'
    )  # Is this stripping? ` --tags1 f f ' '` parses as ['f', 'f']?

    showall = kwconf.Flag(help='print work without doing it')

    dry_run = kwconf.Flag(False, help='print work without doing it')


def main(argv=None):
    print_rule('This demo will only print modified values:')
    config = JonsConfig.cli(argv=argv)
    print_resolved_config(config, explicit_only=not config.showall)
    return config


if __name__ == '__main__':
    main()
