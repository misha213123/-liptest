#!/usr/bin/env python3
"""JSON bridge for the HDRezka film/series catalog endpoint."""
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from film_catalog import catalog

if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Передай ссылку на страницу фильма или сериала.")
        print(json.dumps(catalog(sys.argv[1]), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
