"""App que levanta uvicorn.

`uv run uvicorn radia.backend.api.main:app --reload --port 8000`
Documentación interactiva: http://localhost:8000/docs
"""

from radia.backend.api.app import create_app

app = create_app()
