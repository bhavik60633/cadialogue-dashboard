"""Shared path constant for the generated-images directory."""
from pathlib import Path

IMAGES_DIR = Path(__file__).resolve().parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)
