"""Rebuilds data/<year> from the sources in its config.json.

Usage: python3 -I pipeline/run.py <year> <work_dir>
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "tests")]
import appendix_b  # noqa: E402
import years  # noqa: E402


def get(url, path):
    if not (os.path.exists(path) and os.path.getsize(path)):
        subprocess.run(["curl", "-sS", "-L", "--fail", "--max-time", "900", "-A", "Mozilla/5.0", "-o", path, url],
                       check=True)


def py(script, *args):
    subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *map(str, args)], check=True)


def main(year, work):
    data = years.data_dir(year)
    config = years.config(data)
    work = os.path.abspath(work)
    os.makedirs(work, exist_ok=True)
    get(config["landscape_zip"], f"{work}/landscape.zip")
    get(config["pbp_zip"], f"{work}/pbp.zip")
    subprocess.run(["unzip", "-oq", f"{work}/landscape.zip", "-d", work], check=True)
    subprocess.run(["unzip", "-oq", f"{work}/pbp.zip", "-d", f"{work}/pbp"], check=True)

    py("universe.py", f"{work}/{config['landscape_csv']}", data / "plans.csv", config["state"], *config["counties"])
    baseline = [years.REPO / config["baseline_manifest"]] if "baseline_manifest" in config else []
    py("fetch_docs.py", data / "documents.csv", data / "plans.csv", f"{work}/docs", data / "documents_checked.csv",
       config["year"], ",".join(config["counties"]), *baseline)
    py("cite.py", data / "sb_facts.csv", data / "documents_checked.csv", f"{work}/docs/text", data / "citations.csv")
    py("main_chart.py", data / "plans.csv", f"{work}/pbp", data / "citations.csv", data / "main_chart.csv",
       data / "pbp_vs_documents.csv")
    py("dvha.py", data / "plans.csv", f"{work}/pbp", data / "citations.csv", data / "dvha.csv",
       data / "pbp_vs_documents_dvha.csv")
    if config["year"] == appendix_b.YEAR:
        py("tests/make_fixture.py", f"{work}/pbp")
    subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", os.path.join(HERE, "tests")], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
