from __future__ import annotations

import os
from contextlib import contextmanager
from os.path import exists
from typing import IO, Any, Iterator, Union


@contextmanager
def open_text_input(
    path_or_file: Union[str, os.PathLike, IO[Any]], mode: str = 'r'
) -> Iterator[IO[Any]]:
    """
    Yield a readable file object from either a path or an already-open file.

    A path is opened (and closed on exit). An already-open file object is
    yielded as-is and left open, so a caller-supplied stream is never closed by
    us. ``mode`` must be readable.

    Args:
        path_or_file (str | os.PathLike | IO): a path to open or a readable file
        mode (str): file mode; must contain ``'r'``

    Yields:
        IO: the readable file object
    """
    if 'r' not in mode:
        raise ValueError('file must be readable')
    if isinstance(path_or_file, (str, os.PathLike)):
        fspath = os.fspath(path_or_file)
        if not exists(fspath):
            raise ValueError('Path {} does not exist'.format(fspath))
        with open(fspath, mode) as file:
            yield file
    elif hasattr(path_or_file, 'readable'):
        if not path_or_file.readable():
            raise ValueError('file must be readable')
        yield path_or_file
    else:
        raise TypeError('input must be a path or readable file')
