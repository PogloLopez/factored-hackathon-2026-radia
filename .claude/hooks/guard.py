"""PreToolUse hook de Claude Code. Bloquea con exit 2 (el motivo le llega al agente).

1. Leer, editar o imprimir .env (se permite .env.example) y los PDF de docs/pdf.
2. Commit, merge o push directo sobre main o develop.
3. git commit si ruff falla.
"""

import json
import re
import subprocess
import sys
from pathlib import PurePath

PROTECTED = {"main", "develop"}
ENV_IN_TEXT = re.compile(r"(?<![\w.-])\.env(?!\.example)(\.[\w-]+)?(?![\w.-])")
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}


def block(reason: str) -> None:
    print(f"BLOQUEADO por .claude/hooks/guard.py: {reason}", file=sys.stderr)
    sys.exit(2)


def is_secret_path(path: str) -> bool:
    p = PurePath(path.replace("\\", "/"))
    if p.name == ".env" or (p.name.startswith(".env.") and p.name != ".env.example"):
        return True
    return "docs/pdf" in p.as_posix() or p.suffix.lower() == ".pdf"


def current_branch() -> str:
    out = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
    return out.stdout.strip()


def check_bash(cmd: str) -> None:
    if ENV_IN_TEXT.search(cmd):
        block("el comando toca .env. Los secretos no se leen ni se imprimen.")
    if "docs/pdf" in cmd:
        block("docs/pdf contiene credenciales.")

    branch = current_branch()
    for part in re.split(r"&&|\|\||;|\n", cmd):
        part = part.strip()
        if not part.startswith("git "):
            continue
        if re.match(r"git\s+push\b", part):
            targets = set(re.findall(r"[\w./-]+", part)) & PROTECTED
            refspecs = {t.split(":")[-1] for t in re.findall(r"\S+:\S+", part)} & PROTECTED
            if targets or refspecs or (branch in PROTECTED and len(part.split()) <= 3):
                block("push directo a main/develop. Abre un PR desde tu rama.")
        if re.match(r"git\s+merge\b", part) and branch in PROTECTED:
            block(f"merge directo sobre {branch}. Se integra por PR.")
        if re.match(r"git\s+commit\b", part):
            if branch in PROTECTED:
                block(f"commit directo sobre {branch}. Crea una rama feat/... primero.")
            for ruff in (["ruff", "check", "."], ["ruff", "format", "--check", "."]):
                res = subprocess.run(["uv", "run", *ruff], capture_output=True, text=True)
                if res.returncode != 0:
                    fix = "uv run ruff check --fix . && uv run ruff format ."
                    block(f"ruff falló. Corre `{fix}`\n{res.stdout[-1500:]}")


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    if tool in FILE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if is_secret_path(path):
            block(f"acceso a {path} no permitido.")
    elif tool == "Bash":
        check_bash(inp.get("command", ""))
    elif tool in {"Grep", "Glob"}:
        target = f"{inp.get('path', '')} {inp.get('glob', '')} {inp.get('pattern', '')}"
        if ENV_IN_TEXT.search(target):
            block("búsqueda sobre .env no permitida.")


if __name__ == "__main__":
    main()
