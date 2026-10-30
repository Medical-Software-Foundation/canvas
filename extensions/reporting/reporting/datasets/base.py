"""Dataset type definitions.

Kept in a leaf module (no registry, no side-effect imports) so dataset modules and
the package __init__ can import these types via full submodule paths without creating
an import cycle. The Canvas sandbox re-evaluates modules on each import (no sys.modules
caching), so cyclic imports and cross-module mutable singletons must be avoided.
"""

from dataclasses import dataclass
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
    # For category fields with a fixed enum: the allowed (value, label) options the
    # UI offers as a multi-select.
    choices: tuple[tuple[str, str], ...] = ()
    # For reference fields whose options are live instance data (e.g. providers,
    # locations): the ORM paths used to fetch distinct (value, label) options from
    # the dataset's model. When set, the UI shows a multi-select populated on demand.
    # Empty choices AND empty options_value_path -> free-text input (e.g. numbers).
    options_value_path: str | None = None
    options_label_paths: tuple[str, ...] = ()


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
