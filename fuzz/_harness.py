"""Shared set-up for the fuzz targets: put scripts/ on sys.path and run a target either under
atheris (ClusterFuzzLite) or, without it, over the seed inputs given on the command line, which is
how tests/test_contract.py exercises every target on each CI run."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
if os.path.isdir(SCRIPTS):
    sys.path.insert(0, SCRIPTS)
else:  # PyInstaller bundle built by ClusterFuzzLite: the modules are next to the target
    sys.path.insert(0, HERE)


def main(test_one_input):
    try:
        import atheris
    except ImportError:
        for path in sys.argv[1:]:
            with open(path, "rb") as f:
                test_one_input(f.read())
        return
    atheris.instrument_all()
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
