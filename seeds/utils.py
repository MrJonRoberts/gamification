from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Type

from app.extensions import db


def get_or_create(model: Type[db.Model], defaults: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Tuple[db.Model, bool]:
    instance = model.query.filter_by(**kwargs).first()
    if instance:
        return instance, False

    params = {**kwargs, **(defaults or {})}
    instance = model(**params)
    db.session.add(instance)
    db.session.flush()
    return instance, True

