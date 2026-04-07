#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import kwconf as scfg
from kwconf import __version__


class KwconfModal(scfg.ModalCLI):
    """
    Top level modal CLI for kwconf helpers
    """
    __version__ = __version__
    from kwconf._cli.template import TemplateCLI as template


__cli__ = KwconfModal
main = __cli__.main


if __name__ == '__main__':
    """
    CommandLine:
        python -m kwconf
    """
    main()
