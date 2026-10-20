"""Audit every mcp.call() site: which use positional args (a schema risk)."""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CALL = re.compile(r"mcp\.call\(\s*([\"'])([a-z_]+)\1\s*,?\s*([^)]*)\)", re.S)

root = Path(__file__).resolve().parent.parent
for f in sorted(root.rglob("*.py")):
    if any(p in f.parts for p in (".venv", "tests", "__pycache__")):
        continue
    s = f.read_text(encoding="utf-8")
    for m in CALL.finditer(s):
        name, rest = m.group(2), m.group(3)
        ln = s[: m.start()].count("\n") + 1
        # a bare positional is an arg with no '=' at top level
        pos = []
        for part in re.split(r",(?![^(]*\))", rest):
            part = part.strip()
            if part and "=" not in part:
                pos.append(part)
        flag = "POSITIONAL" if pos else "kw-only "
        print(f"{flag} {f.relative_to(root)}:{ln}  {name}  {pos or ''}")
