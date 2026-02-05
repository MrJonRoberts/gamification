from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import inspect
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.properties import ColumnProperty, SynonymProperty


def get_model_attribute(model: type, name: str) -> Optional[InstrumentedAttribute]:
    """Return a mapped column/synonym attribute or None if it is not present."""
    try:
        mapper = inspect(model)
    except Exception:
        return None

    prop = mapper.attrs.get(name)
    if not isinstance(prop, (ColumnProperty, SynonymProperty)):
        return None

    return getattr(model, name, None)


def first_model_attribute(model: type, names: Iterable[str]) -> Optional[InstrumentedAttribute]:
    """Return the first mapped column/synonym attribute from the provided names."""
    for name in names:
        attr = get_model_attribute(model, name)
        if attr is not None:
            return attr
    return None
