from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .build import build_files, prepare, write_files
from .parse import json_schema, load_file
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


def cmd_check(args) -> int:
    status = 0
    for f in args.files:
        try:
            p = prepare(load_file(f), args.theme)
        except DiagramError as e:
            _report(e.problems)
            status = 1
            continue
        _report(p.warnings)
        if args.strict and p.warnings:
            status = 1
        if not p.warnings:
            print(f"{f}: ok")
    return status


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
    c.set_defaults(fn=cmd_check)

    s = sub.add_parser("schema", help="print the JSON Schema for diagram files")
    s.add_argument("--out", "-o")
    s.set_defaults(fn=cmd_schema)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
