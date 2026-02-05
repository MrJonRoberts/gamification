from typing import Any
from fastapi import Request


def url_for(request: Request, name: str, **params: Any) -> str:
    """
    Helper to generate URLs for routes, with special handling for static files
    and graceful error handling if a route is not found.
    """
    if name == "static":
        path = params.get("filename", "")
        return str(request.url_for("static", path=path))
    try:
        return str(request.url_for(name, **params))
    except Exception:
        return "#"


def flash(request: Request, message: str, category: str = "info") -> None:
    """
    Adds a flash message to the session to be displayed on the next request.
    """
    messages = request.session.setdefault("_flashes", [])
    messages.append((category, message))
    request.session["_flashes"] = messages


def get_flashed_messages(request: Request, with_categories: bool = True) -> list[Any]:
    """
    Retrieves and clears flash messages from the session.
    """
    messages = request.session.pop("_flashes", [])
    if not with_categories:
        return [message for _, message in messages]
    return messages
