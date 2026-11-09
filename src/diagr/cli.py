from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from . import __version__
from .build import build_files, prepare, write_files
from .icons import CORE, Icons
from .parse import ID, json_schema, load_file
from .source import DiagramError, Problem


def _report(problems: list[Problem]) -> None:
    for p in problems:
        print(p, file=sys.stderr)


def cmd_build(args) -> int:
    status = 0
    built: dict[str, str] = {}
    for f in args.files:
        try:
            d = load_file(f)
            if d.id in built:
                raise DiagramError([Problem(None, f"{f}: diagram id '{d.id}' is also used by {built[d.id]}; "
                                                 "their output files would overwrite each other")])
            built[d.id] = f
            p = prepare(d, args.theme)
            written = write_files(p, args.out)
        except DiagramError as e:
            _report(e.problems)
            status = 1
            continue
        except OSError as e:
            print(f"error: cannot write to {args.out}: {e.strerror or e}", file=sys.stderr)
            return 1
        _report(p.warnings)
        for w in written:
            print(w)
    return status


def _as_json(f: str, p: Problem) -> dict:
    loc = p.loc
    return {"file": loc.file if loc else f, "line": loc.line if loc else None, "col": loc.col if loc else None,
            "level": p.level, "message": p.message}


def cmd_check(args) -> int:
    status = 0
    found: list[dict] = []
    for f in args.files:
        try:
            problems = prepare(load_file(f), args.theme).warnings
            if args.strict and problems:
                status = 1
        except DiagramError as e:
            problems = e.problems
            status = 1
        if args.format == "json":
            found += [_as_json(f, p) for p in problems]
            continue
        _report(problems)
        if not problems:
            print(f"{f}: ok")
    if args.format == "json":
        print(json.dumps(found, indent=2))
    return status


def cmd_icons(args) -> int:
    folders: list[Path] = []
    if args.file:
        try:
            d = load_file(args.file)
        except DiagramError as e:
            _report(e.problems)
            return 1
        folders = [(d.base / f).resolve() for f in d.icons]
    icons = Icons(folders)
    _report(icons.problems)
    for f in icons.missing:
        print(f"warning: icon folder not found: {f}", file=sys.stderr)
    rows = icons.available()
    width = max((len(name) for name, _, _ in rows), default=0)
    for name, kind, folder in rows:
        print(f"{name:<{width}}  {kind:<4}  {'core' if folder == CORE else folder}")
    return 0


STARTER = Path(__file__).resolve().parent / "starter.yml"


def cmd_init(args) -> int:
    path = Path(args.file)
    if path.exists():
        print(f"error: {path} already exists", file=sys.stderr)
        return 1
    name = args.id or (path.stem if path.stem != "diagram" else path.resolve().parent.name)
    did = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "diagram"
    if not re.fullmatch(ID, did):
        did = f"d-{did}"
    text = STARTER.read_text(encoding="utf-8").replace("diagram: order-flow", f"diagram: {did}", 1)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"error: cannot write {path}: {e.strerror or e}", file=sys.stderr)
        return 1
    print(path)
    print(f"next: diagr build {path}", file=sys.stderr)
    return 0


def cmd_schema(args) -> int:
    text = json.dumps(json_schema(), indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def _watched(f: Path, theme_override: str | None) -> list[Path]:
    paths = [f]
    try:
        d = load_file(f)
        for folder in d.icons:
            paths += sorted((d.base / folder).glob("*"))
        theme = Path(theme_override) if theme_override else d.base / d.theme
        if theme.is_file():
            paths.append(theme)
    except DiagramError:
        pass
    return paths


def _stamp(paths: list[Path]) -> tuple:
    out = []
    for p in paths:
        try:
            out.append((str(p), p.stat().st_mtime_ns))
        except FileNotFoundError:
            out.append((str(p), None))
    return tuple(out)


def cmd_watch(args) -> int:
    files = [Path(f) for f in args.files]
    stamps: dict[Path, tuple] = {}
    print(f"watching {len(files)} file(s), Ctrl-C to stop", file=sys.stderr)
    try:
        while True:
            for f in files:
                s = _stamp(_watched(f, args.theme))
                if stamps.get(f) != s:
                    stamps[f] = s
                    try:
                        written, warnings = build_files(f, args.out, args.theme)
                        _report(warnings)
                        print(f"{time.strftime('%H:%M:%S')} built {', '.join(w.name for w in written)}")
                    except DiagramError as e:
                        _report(e.problems)
                    except OSError as e:
                        print(f"error: cannot write to {args.out}: {e.strerror or e}", file=sys.stderr)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="diagr", description="Declarative diagrams: static SVG and interactive HTML.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write <id>-light.svg, <id>-dark.svg and <id>.html")
    b.add_argument("files", nargs="+")
    b.add_argument("--out", "-o", default="dist")
    b.add_argument("--theme", help="override the diagram's theme")
    b.set_defaults(fn=cmd_build)

    w = sub.add_parser("watch", help="rebuild when the file, its icons or its theme change")
    w.add_argument("files", nargs="+")
    w.add_argument("--out", "-o", default="dist")
    w.add_argument("--theme")
    w.add_argument("--interval", type=float, default=0.5)
    w.set_defaults(fn=cmd_watch)

    c = sub.add_parser("check", help="validate without writing files")
    c.add_argument("files", nargs="+")
    c.add_argument("--theme")
    c.add_argument("--strict", action="store_true", help="treat warnings as errors")
    c.add_argument("--format", choices=("text", "json"), default="text",
                   help="json prints every problem as a list of {file, line, col, level, message} on stdout")
    c.set_defaults(fn=cmd_check)

    i = sub.add_parser("init", help="write a starter diagram")
    i.add_argument("file", nargs="?", default="diagram.yml")
    i.add_argument("--id", help="diagram id; default: the file name, or the folder name for diagram.yml")
    i.set_defaults(fn=cmd_init)

    n = sub.add_parser("icons", help="list the icons a diagram can use")
    n.add_argument("file", nargs="?", help="a diagram, to include its icon folders")
    n.set_defaults(fn=cmd_icons)

    s = sub.add_parser("schema", help="print the JSON Schema for diagram files")
    s.add_argument("--out", "-o")
    s.set_defaults(fn=cmd_schema)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
