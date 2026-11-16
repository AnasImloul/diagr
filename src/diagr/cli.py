from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from . import __version__
from .build import prepare_all, write_files
from .icons import CORE, Icons
from .migrations import upgrade
from .model import Diagram
from .parse import load_file
from .source import DiagramError, Problem, data, load
from .syntax import ID, json_schema
from .theme import theme_files


def _report(problems: list[Problem]) -> None:
    for p in problems:
        print(p, file=sys.stderr)


def _outputs(d: Diagram) -> dict[str, str]:
    """The name each of the diagram's pages is written under, with its SVGs, and what writes it."""
    return {d.id: f"diagram '{d.id}'"} | {f"{d.id}-{v}": f"view '{v}' of '{d.id}'" for v in d.views}


def _claim(names: dict[str, tuple[str, str]], f: str, d: Diagram) -> None:
    """Claims d's output names for file f, giving up those f wrote before; raises if another file writes one of them.
    names maps each output name to the file that writes it and what in that file does."""
    mine = _outputs(d)
    for name, what in mine.items():
        if name in names and names[name][0] != f:
            other, theirs = names[name]
            raise DiagramError(
                [Problem(None, f"{f}: {what} writes {name}.html and its SVGs, which {theirs} in {other} also writes")]
            )
    for name in [n for n, (g, _) in names.items() if g == f]:
        del names[name]
    names.update({name: (f, what) for name, what in mine.items()})


def cmd_build(args) -> int:
    status = 0
    names: dict[str, tuple[str, str]] = {}
    for f in args.files:
        try:
            d = load_file(f)
            _claim(names, f, d)
            ps = prepare_all(d, args.theme)
            written = [w for p in ps for w in write_files(p, args.out, debug=args.debug, transparent=args.transparent)]
        except DiagramError as e:
            _report(e.problems)
            status = 1
            continue
        except OSError as e:
            print(f"error: cannot write to {args.out}: {e.strerror or e}", file=sys.stderr)
            return 1
        _report([w for p in ps for w in p.warnings])
        for w in written:
            print(w)
    return status


def _as_json(f: str, p: Problem) -> dict:
    loc = p.loc
    return {
        "file": loc.file if loc else f,
        "line": loc.line if loc else None,
        "col": loc.col if loc else None,
        "level": p.level,
        "message": p.message,
    }


def cmd_check(args) -> int:
    status = 0
    found: list[dict] = []
    for f in args.files:
        try:
            problems = [w for p in prepare_all(load_file(f), args.theme) for w in p.warnings]
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


def cmd_expand(args) -> int:
    from .unparse import to_yaml

    try:
        d = load_file(args.file)
        source = data(upgrade(load(Path(args.file).read_text(encoding="utf-8"), args.file))[0])
        text = to_yaml(d, source)
    except DiagramError as e:
        _report(e.problems)
        return 1
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


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
    text = STARTER.read_text(encoding="utf-8").replace("id: order-flow", f"id: {did}", 1)
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
        if theme_override:
            paths += theme_files(theme_override, Path.cwd())
        else:
            paths += theme_files(d.theme, d.base)
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
    names: dict[str, tuple[str, str]] = {}
    server = None
    if args.serve:
        from .live import LiveServer

        try:
            server = LiveServer(Path(args.out), args.port)
        except OSError as e:
            print(f"error: cannot serve on port {args.port}: {e.strerror or e}", file=sys.stderr)
            return 1
        print(f"serving {args.out} at http://127.0.0.1:{server.port}/", file=sys.stderr)
    print(f"watching {len(files)} file(s), Ctrl-C to stop", file=sys.stderr)
    try:
        while True:
            for f in files:
                s = _stamp(_watched(f, args.theme))
                if stamps.get(f) != s:
                    stamps[f] = s
                    try:
                        d = load_file(f)
                        _claim(names, str(f), d)
                        ps = prepare_all(d, args.theme)
                        written = [
                            w
                            for p in ps
                            for w in write_files(
                                p, args.out, debug=args.debug, live=bool(server), transparent=args.transparent
                            )
                        ]
                        _report([w for p in ps for w in p.warnings])
                        print(f"{time.strftime('%H:%M:%S')} built {', '.join(w.name for w in written)}")
                        if server:
                            server.bump()
                    except DiagramError as e:
                        _report(e.problems)
                    except OSError as e:
                        print(f"error: cannot write to {args.out}: {e.strerror or e}", file=sys.stderr)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        if server:
            server.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="diagr", description="Declarative diagrams: static SVG and interactive HTML.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write <id>-light.svg, <id>-dark.svg and <id>.html")
    b.add_argument("files", nargs="+")
    b.add_argument("--out", "-o", default="dist")
    b.add_argument("--theme", help="override the diagram's theme")
    b.add_argument("--debug", action="store_true", help="add the grid and route overlay to the HTML page (G toggles)")
    b.add_argument(
        "--transparent", action="store_true", help="leave the background out of the SVGs, for a page of any colour"
    )
    b.set_defaults(fn=cmd_build)

    w = sub.add_parser("watch", help="rebuild when the file, its icons or its theme change")
    w.add_argument("files", nargs="+")
    w.add_argument("--out", "-o", default="dist")
    w.add_argument("--theme")
    w.add_argument("--debug", action="store_true", help="add the grid and route overlay to the HTML page (G toggles)")
    w.add_argument(
        "--transparent", action="store_true", help="leave the background out of the SVGs, for a page of any colour"
    )
    w.add_argument("--serve", action="store_true", help="serve the output on localhost; open pages reload on rebuild")
    w.add_argument("--port", type=int, default=8001, help="port for --serve (default 8001)")
    w.add_argument("--interval", type=float, default=0.5)
    w.set_defaults(fn=cmd_watch)

    c = sub.add_parser("check", help="validate without writing files")
    c.add_argument("files", nargs="+")
    c.add_argument("--theme")
    c.add_argument("--strict", action="store_true", help="treat warnings as errors")
    c.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="json prints every problem as a list of {file, line, col, level, message} on stdout",
    )
    c.set_defaults(fn=cmd_check)

    i = sub.add_parser("init", help="write a starter diagram")
    i.add_argument("file", nargs="?", default="diagram.yml")
    i.add_argument("--id", help="diagram id; default: the file name, or the folder name for diagram.yml")
    i.set_defaults(fn=cmd_init)

    x = sub.add_parser("expand", help="print the diagram with components expanded into plain groups, nodes and edges")
    x.add_argument("file")
    x.add_argument("--out", "-o")
    x.set_defaults(fn=cmd_expand)

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
