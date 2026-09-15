"""Export the FastAPI contract in a stable, reviewable form."""
import json
from pathlib import Path

from backend.app.main import create_app

output = Path(__file__).resolve().parents[1] / "openapi.json"
output.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
