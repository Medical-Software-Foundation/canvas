"""Dataset registry: declarative bindings of friendly fields/measures to ORM models.

The registry lives entirely in this module and is built by importing each built-in
dataset's pure-data ``DATASET`` constant via a full submodule path. We deliberately
avoid `from reporting.datasets import <sub>` (which re-evaluates this package in the
Canvas sandbox and recurses) and avoid cross-module mutable registration (the sandbox
re-evaluates modules without sys.modules caching, so a shared mutable registry would
fragment across module instances).
"""

from reporting.datasets.appointments import DATASET as _APPOINTMENTS_DATASET
from reporting.datasets.base import Dataset, Dimension, Field
from reporting.datasets.claims import DATASET as _CLAIMS_DATASET
from reporting.datasets.encounters import DATASET as _ENCOUNTERS_DATASET
from reporting.datasets.patients import DATASET as _PATIENTS_DATASET

_BUILTIN_DATASETS = (
    _APPOINTMENTS_DATASET,
    _PATIENTS_DATASET,
    _ENCOUNTERS_DATASET,
    _CLAIMS_DATASET,
)
_REGISTRY: dict[str, Dataset] = {d.key: d for d in _BUILTIN_DATASETS}

__all__ = ["Dataset", "Dimension", "Field", "get_dataset", "list_datasets"]


def get_dataset(key: str) -> Dataset:
    if key not in _REGISTRY:
        raise KeyError(f"Unknown dataset: {key}")
    return _REGISTRY[key]


def list_datasets() -> list[Dataset]:
    return list(_REGISTRY.values())
