"""Each plan year's data lives in data/<year>, with its sources listed in config.json."""
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE = 2027  # The year the site shows.


def data_dir(year=LIVE):
    return REPO / "data" / str(year)


def config(data):
    """config.json, plus the year that names the directory."""
    data = pathlib.Path(data)
    return {**json.loads((data / "config.json").read_text()), "year": int(data.name)}


if __name__ == "__main__":
    print(data_dir().relative_to(REPO))
