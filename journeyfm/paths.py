import os
from pathlib import Path


def get_data_dir() -> Path:
    data_dir = os.getenv("JOURNEYFM_DATA_DIR", "").strip()
    if data_dir:
        path = Path(data_dir)
    else:
        path = Path(".")
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_path(*parts: str) -> Path:
    return get_data_dir().joinpath(*parts)