from fastapi.templating import Jinja2Templates
from .utils import url_for, get_flashed_messages
from .config import settings

templates = Jinja2Templates(directory="app/templates")

def _csrf_token() -> str:
    return ""

def render_template(template_name: str, context: dict):
    request = context.get("request")

    # Standard context variables
    standard_context = {
        "config": settings,
        "url_for": lambda name, **params: url_for(request, name, **params),
        "get_flashed_messages": lambda with_categories=True: get_flashed_messages(
            request, with_categories=with_categories
        ),
        "csrf_token": _csrf_token,
        "getattr": getattr,
    }

    # Merge standard context with provided context
    # Provided context takes precedence
    full_context = {**standard_context, **context}

    return templates.TemplateResponse(template_name, full_context)
