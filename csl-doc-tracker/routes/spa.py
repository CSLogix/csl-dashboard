"""
React SPA serving routes: /, /app, /app/{path}.
"""
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

log = logging.getLogger(__name__)
router = APIRouter()

_react_dist = Path(__file__).parent.parent / "static" / "dist"
_react_index = _react_dist / "index.html"


@router.get("/")
async def react_root():
    """Redirect root to React app."""
    return RedirectResponse("/app", status_code=302)


@router.get("/app")
@router.get("/app/{path:path}")
async def react_spa(path: str = ""):
    """Serve React SPA for all /app/* routes."""
    # Serve actual static files from dist/ if they exist (images, etc.)
    if path:
        import mimetypes as _mt
        static_file = _react_dist / path
        if static_file.is_file():
            mime, _ = _mt.guess_type(str(static_file))
            return FileResponse(str(static_file), media_type=mime or "application/octet-stream")
    if _react_index.exists():
        return FileResponse(str(_react_index), media_type="text/html")
    return RedirectResponse("/legacy", status_code=302)
