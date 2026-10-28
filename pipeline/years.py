"""Each plan year's data lives in data/<year>, with its sources listed in config.json."""
import json
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE = 2027  # The year the site shows.


def data_dir(year=LIVE):
    """SHIBA_DATA names another data root, such as rebuild.py's copy."""
    root = os.environ.get("SHIBA_DATA")
    return (pathlib.Path(root) if root else REPO / "data") / str(year)


def config(data):
    """config.json, plus the year that names the directory."""
    data = pathlib.Path(data)
    return {**json.loads((data / "config.json").read_text()), "year": int(data.name)}


if __name__ == "__main__":
    print(data_dir().relative_to(REPO))
