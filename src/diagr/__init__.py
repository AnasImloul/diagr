from importlib.metadata import PackageNotFoundError, version

from .build import Prepared, build_files, prepare
from .model import Diagram
from .parse import load_file
from .source import DiagramError, Problem
from .syntax import json_schema

__all__ = ["Diagram", "DiagramError", "Prepared", "Problem", "build_files", "json_schema", "load_file", "prepare"]
try:
    __version__ = version("diagr")
except PackageNotFoundError:
    __version__ = "0+unknown"
