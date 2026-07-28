import importlib.util
import sys
from pathlib import Path

# Only add the repo root to sys.path when kwconf is not already importable
# (e.g. a bare checkout with no editable/installed package). The CI sdist and
# wheel jobs deliberately run the tests against the *installed* artifact from a
# sandbox directory; unconditionally prepending the repo root would shadow that
# install with the source checkout and quietly defeat those jobs.
if importlib.util.find_spec('kwconf') is None:
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
