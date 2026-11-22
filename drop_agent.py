"""Vecchio nome di Archeo. Usa `archeo.py`. Verrà rimosso al prossimo rilascio."""
import sys
import warnings

warnings.warn("drop_agent.py è deprecato: usa archeo.py", DeprecationWarning, stacklevel=2)

from archeo import *  # noqa: F401,F403
from archeo import main as _main
from archeo import run_archeo as run_drop_agent  # Backward-compatible Python API

if __name__ == "__main__":
    sys.exit(_main())
