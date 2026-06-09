"""Dataset definitions: declarative bindings of friendly fields/measures to ORM models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reporting.query.measures import Measure


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    type: str               # person|place|category|number|date|money|boolean
    orm_path: str
    filterable: bool = False
    operators: tuple[str, ...] = ()
    groupable: bool = False


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    group_path: str             # ORM path used in .values(...)
    display_paths: list[str]    # extra .values(...) paths for human labels


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    model: Any                  # the ORM model class
    date_field: str             # field used for period range filtering
    fields: dict[str, Field]
    dimensions: dict[str, Dimension]
    measures: dict[str, Measure]


_REGISTRY: dict[str, Dataset] = {}


def register(dataset: Dataset) -> None:
    _REGISTRY[dataset.key] = dataset


def get_dataset(key: str) -> Dataset:
    if key not in _REGISTRY:
        raise KeyError(f"Unknown dataset: {key}")
    return _REGISTRY[key]


def list_datasets() -> list[Dataset]:
    return list(_REGISTRY.values())


# Import side-effect: register built-in datasets.
from reporting.datasets import appointments as _appointments  # noqa: E402,F401
