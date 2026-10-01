from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gltg_runtime_does_not_import_aivan() -> None:
    """GLTG is independently deployable; Aivan integrates only over HTTP."""

    violations: list[str] = []
    for path in (ROOT / "src" / "gltg").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "aivan" or name.startswith("aivan.") for name in names):
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []
