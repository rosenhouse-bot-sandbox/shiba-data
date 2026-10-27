"""Each plan year's data lives in data/<year>, with its sources listed in config.json."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "data"


def data_dir(year=None):
    """data/<year>, or the newest year's directory."""
    return ROOT / str(year or max(p.name for p in ROOT.iterdir() if p.name.isdigit()))


def config(data):
    return json.loads((pathlib.Path(data) / "config.json").read_text())
