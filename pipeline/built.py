"""Splits the tests into code tests and checks of a year's built data.

Usage: python3 -I pipeline/built.py code|checks

Code tests must pass without OUTPUTS and RUN_STATE, so they run against a copy of data/ without them.
Checks are tests marked with @built.check. They read the data a run builds, so run.py runs them after its model steps.
"""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import years  # noqa: E402

TESTS = HERE / "tests"
# What a replay writes into data/<year>.
OUTPUTS = ("machine/document_facts.csv", "generated/plans.csv", "generated/landscape_reads.csv",
           "generated/pbp_facts.csv", "generated/cms_sources.csv", "generated/presented.csv",
           "generated/main_chart.csv", "generated/dvha.csv")
# What each run reads from earlier runs.
RUN_STATE = ("answers", "evaluations/imaging/answers", "machine/reviewed_facts.csv")


def check(test):
    """Marks a test method or class that reads a year's built data."""
    test.checks_built_data = True
    return test


def tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from tests(test)
        else:
            yield test


def is_check(test):
    method = getattr(test, getattr(test, "_testMethodName", ""), None)
    return getattr(method, "checks_built_data", False) or getattr(type(test), "checks_built_data", False)


def split(suite):
    """(code tests, checks)"""
    code, checks = unittest.TestSuite(), unittest.TestSuite()
    for test in tests(suite):
        (checks if is_check(test) else code).addTest(test)
    return code, checks


def without_built(root, dest):
    """Copies the data root without any year's OUTPUTS or RUN_STATE."""
    left_out = {f"{year.name}/{p}" for year in pathlib.Path(root).iterdir() for p in OUTPUTS + RUN_STATE}
    shutil.copytree(root, dest, ignore=lambda d, names: [
        n for n in names if pathlib.Path(d, n).relative_to(root).as_posix() in left_out])


def run(kind):
    code, checks = split(unittest.TestLoader().discover(str(TESTS)))
    return unittest.TextTestRunner().run(code if kind == "code" else checks).wasSuccessful()


def main(kind):
    """Runs one kind of test, and says whether they all passed."""
    if kind == "checks":
        return run(kind)
    with tempfile.TemporaryDirectory() as tmp:
        without_built(years.data_dir().parent, f"{tmp}/data")
        saved = os.environ.get("SHIBA_DATA")
        os.environ["SHIBA_DATA"] = f"{tmp}/data"
        try:
            return run(kind)
        finally:
            if saved is None:
                del os.environ["SHIBA_DATA"]
            else:
                os.environ["SHIBA_DATA"] = saved


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("code", "checks"):
        raise SystemExit(__doc__)
    sys.exit(not main(sys.argv[1]))
