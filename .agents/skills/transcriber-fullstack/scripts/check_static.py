#!/usr/bin/env python3
"""Check source syntax without importing the app or contacting services."""

import ast
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys


class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attrs = dict(attrs)
        script_type = attrs.get("type", "").strip().lower()
        if "src" not in attrs and script_type in (
            "", "text/javascript", "application/javascript", "module"
        ):
            self.current = (script_type == "module", [])

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            module, parts = self.current
            source = "".join(parts)
            if source.strip():
                self.scripts.append((module, source))
            self.current = None


def main():
    root = Path(__file__).resolve().parents[4]
    if not (root / "frontend").is_dir() or not (root / "backend").is_dir():
        print("FAIL: expected skill inside the Web Transcriber repository", file=sys.stderr)
        return 1

    failures = []
    counts = {"Python": 0, "JavaScript files": 0, "inline scripts": 0, "shell": 0}
    node = shutil.which("node")
    bash = shutil.which("bash")
    for name, binary in (("node", node), ("bash", bash)):
        if binary is None:
            failures.append(f"missing required tool: {name}")

    def check(command, label, source=None):
        result = subprocess.run(
            command, input=source, text=True, capture_output=True, cwd=root, timeout=30
        )
        if result.returncode:
            failures.append(f"{label}:\n{result.stderr.strip() or result.stdout.strip()}")

    python_files = sorted(
        p for folder in (root / "backend", root / "tests", Path(__file__).parent)
        for p in folder.rglob("*.py")
    )
    for path in python_files:
        counts["Python"] += 1
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path.relative_to(root)))
        except SyntaxError as error:
            failures.append(f"{path.relative_to(root)}:{error.lineno}: {error.msg}")

    if node:
        for path in sorted((root / "frontend").glob("*.js")):
            check([node, "--check", str(path)], str(path.relative_to(root)))
            counts["JavaScript files"] += 1
        for path in sorted((root / "frontend").glob("*.html")):
            parser = InlineScripts()
            parser.feed(path.read_text(encoding="utf-8"))
            for index, (module, source) in enumerate(parser.scripts, 1):
                kind = "module" if module else "commonjs"
                check(
                    [node, "--check", f"--input-type={kind}", "-"],
                    f"{path.relative_to(root)} inline script {index}",
                    source,
                )
                counts["inline scripts"] += 1

    if bash:
        shell_files = [*root.glob("*.sh"), *(root / "tests").rglob("*.sh"),
                       *(root / "backend").rglob("*.sh")]
        for path in sorted(shell_files):
            check([bash, "-n", str(path)], str(path.relative_to(root)))
            counts["shell"] += 1

    for kind, count in counts.items():
        print(f"{kind}: {count} checked")
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    print("Syntax checks FAILED" if failures else "Syntax checks PASSED; runtime not tested")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
