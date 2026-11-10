"""The playground's side of diagr, run by Pyodide in a web worker: YAML in, one rendered file and the problems out."""

import json
import traceback
from pathlib import Path

from diagr.build import prepare_all
from diagr.parse import loads
from diagr.render.html import render_html
from diagr.render.svg import render_static
from diagr.source import DiagramError, Problem

FILE = "diagram.yml"


def _problem(p: Problem) -> dict:
    here = p.loc is not None and p.loc.file == FILE
    message = p.message if here or p.loc is None else f"{p.loc}: {p.message}"
    return {
        "line": p.loc.line if here and p.loc else None,
        "col": p.loc.col if here and p.loc else None,
        "level": p.level,
        "message": message,
    }


def build(text: str, want: str, view: str = "", contrast: bool = False) -> str:
    """`want` is "html", "light" or "dark"; `view` a view's key, or "" for the whole diagram."""
    try:
        d = loads(text, FILE, Path.cwd())
        views = [{"key": "", "title": "Whole diagram"}] + [
            {"key": k, "title": v.title or k} for k, v in d.views.items()
        ]
        ps = prepare_all(d, "contrast" if contrast and want != "html" else None)
    except DiagramError as e:
        return json.dumps({"problems": [_problem(p) for p in e.problems]})
    except Exception:
        return json.dumps({"crash": traceback.format_exc()})
    keys = [v["key"] for v in views]
    p = ps[keys.index(view)] if view in keys else ps[0]
    try:
        out = render_html(p) if want == "html" else render_static(p.scene(), p.theme, want)
    except Exception:
        return json.dumps({"crash": traceback.format_exc()})
    return json.dumps(
        {
            "id": p.diagram.id,
            "views": views,
            "view": view if view in keys else "",
            "scenarios": bool(p.diagram.scenarios),
            "out": out,
            "problems": [_problem(w) for q in ps for w in q.warnings],
        }
    )
