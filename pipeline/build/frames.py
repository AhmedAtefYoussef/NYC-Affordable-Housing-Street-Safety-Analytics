"""Small helpers that shape exported frames: narrow types, fixed category orders, JSON-safe values."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.build.checks import BYTES_PER_MB, PARQUET_OPTIONS, require


def smallest_unsigned(series: pd.Series) -> pd.Series:
    """Cast a non-negative integer column to the narrowest unsigned type that holds it."""
    require((series >= 0).all(), f"{series.name} has negative values")
    return pd.to_numeric(series, downcast="unsigned")


def as_category(values, categories: list[str]) -> pd.Categorical:
    """A categorical with a fixed category order, failing loudly on a label outside it."""
    result = pd.Categorical(values, categories=categories)
    require(not pd.isna(result).any(), f"values outside {categories}")
    return result


def write_table(frame: pd.DataFrame, name: str, out_dir: Path, schema: dict) -> None:
    """Write one parquet file, record its schema for meta.json and print its shape and size."""
    path = out_dir / f"{name}.parquet"
    frame.to_parquet(path, **PARQUET_OPTIONS)
    schema[name] = {column: str(dtype) for column, dtype in frame.dtypes.items()}
    print(f"  {name:<13} {len(frame):>9,} rows x {frame.shape[1]:>2} columns  {path.stat().st_size / BYTES_PER_MB:6.2f} MB")


def to_plain(value):
    """Convert numpy and pandas scalars and containers to JSON-safe Python values."""
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return [to_plain(item) for item in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if value is pd.NA or value is None:
        return None
    return value


def smallest_unsigned_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply `smallest_unsigned` to every column."""
    return frame.apply(smallest_unsigned)
