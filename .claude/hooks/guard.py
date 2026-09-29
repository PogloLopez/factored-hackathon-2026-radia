"""PreToolUse hook de Claude Code. Bloquea con exit 2 (el motivo le llega al agente).

1. Leer, editar o imprimir .env (se permite .env.example) y los PDF de docs/pdf.
2. Commit, merge o push directo sobre main o develop.
3. git commit: formatea y corrige con ruff los archivos del commit y los vuelve a agregar.
   Solo bloquea si queda un error que ruff no puede corregir solo.
4. Cualquier comando `aws s3` o `aws s3api`. El bucket de Factored solo se toca
   desde el módulo de S3 de radia.etl, con un manifiesto aprobado por Pablo.
"""

import json
import re
import subprocess
import sys
from pathlib import PurePath

PROTECTED = {"main", "develop"}
ENV_IN_TEXT = re.compile(r"(?<![\w.-])\.env(?!\.example)(\.[\w-]+)?(?![\w.-])")
# aws o aws.exe (con ruta o comillas) seguido de s3 o s3api.
AWS_S3_CLI = re.compile(
    r"""(?:^|[\s&|;({"'\\/])aws(?:\.exe)?["']?\s+s3(?:api)?\b""", re.IGNORECASE
)
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}


def block(reason: str) -> None:
    print(f"BLOQUEADO por .claude/hooks/guard.py: {reason}", file=sys.stderr)
    sys.exit(2)


def is_secret_path(path: str) -> bool:
    p = PurePath(path.replace("\\", "/"))
    if p.name == ".env" or (p.name.startswith(".env.") and p.name != ".env.example"):
        return True
    return "docs/pdf" in p.as_posix() or p.suffix.lower() == ".pdf"


def current_branch() -> str:
    out = subprocess.run(
        ["git", "branch", "--show-current"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


RUFF_FORMAT = (".py", ".pyi", ".ipynb", ".md")
RUFF_LINT = (".py", ".pyi", ".ipynb")


def git_lines(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return [line for line in out.stdout.splitlines() if line]


def ruff_autofix(all_tracked: bool) -> None:
    """Corrige y formatea solo los archivos del commit y los vuelve a agregar al stage."""
    files = set(git_lines("diff", "--cached", "--name-only", "--diff-filter=ACMR"))
    if all_tracked:
        files |= set(git_lines("diff", "--name-only", "--diff-filter=ACMR"))
    files = sorted(
        f
        for f in files
        if not f.startswith(".claude/") and PurePath(f).suffix in RUFF_FORMAT
    )
    lint = [f for f in files if PurePath(f).suffix in RUFF_LINT]
    if not files:
        return
    if lint:
        subprocess.run(
            ["uv", "run", "ruff", "check", "--fix", "--quiet", *lint],
            capture_output=True,
            text=True,
            check=False,
        )
    subprocess.run(
        ["uv", "run", "ruff", "format", "--quiet", *files],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "add", "--", *files], capture_output=True, text=True, check=False
    )
    if lint:
        res = subprocess.run(
            ["uv", "run", "ruff", "check", *lint],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            block(
                f"ruff corrigió y formateó lo que pudo, pero quedan errores que hay que arreglar a mano:\n{res.stdout[-1500:]}"
            )


# Separadores de comandos en Bash y PowerShell: && || | & ; saltos de línea,
# bloques { } y subexpresiones ( ).
CMD_SEPARATORS = re.compile(r"&&|\|\||[|&;\n\r{}()]")
# Continuación de línea: `\` en Bash y backtick en PowerShell.
LINE_CONTINUATION = re.compile(r"[\\`]\r?\n")
# git o git.exe, con ruta opcional y con o sin comillas, opciones globales
# (con valor tras espacio o "=", entre comillas o no) y el subcomando.
# Análisis textual de mejor esfuerzo. Límites conocidos: un -a después de un
# mensaje con paréntesis no se ve, opciones de push con valor separado
# cuentan como posicionales, y prefijos como `FOO=1 git` o `env git` no se detectan. La garantía dura es la protección de rama en GitHub.
_VALUE = r"""(?:"[^"]*"|'[^']*'|\S+)"""
_GIT_BIN = (
    r"""(?:"(?:[^"]*[\\/])?git(?:\.exe)?"|'(?:[^']*[\\/])?git(?:\.exe)?'"""
    r"""|(?:[^\s"']*[\\/])?git(?:\.exe)?)"""
)
GIT_CMD = re.compile(
    rf"""^{_GIT_BIN}"""
    rf"""((?:\s+(?:(?:-C|-c|--git-dir|--work-tree|--namespace)\s+{_VALUE}"""
    rf"""|--?[\w-]+(?:={_VALUE})?))*)"""
    r"""\s+(push|merge|commit)\b(.*)$""",
    re.IGNORECASE,
)


def git_subcommands(cmd: str) -> list[tuple[str, str]]:
    """Devuelve (subcomando, argumentos) de cada git push/merge/commit del comando."""
    cmd = LINE_CONTINUATION.sub(" ", cmd)
    found = []
    for part in CMD_SEPARATORS.split(cmd):
        match = GIT_CMD.match(part.strip().lstrip("$ "))
        if match:
            found.append((match.group(2).lower(), match.group(3)))
    return found


def check_bash(cmd: str) -> None:
    if ENV_IN_TEXT.search(cmd):
        block("el comando toca .env. Los secretos no se leen ni se imprimen.")
    if re.search(r"docs[\\/]+pdf", cmd, re.IGNORECASE):
        block("docs/pdf contiene credenciales.")
    if AWS_S3_CLI.search(cmd):
        block(
            "la CLI de aws no toca S3. Usa el módulo de S3 de radia.etl "
            "(manifiesto aprobado, descarga única)."
        )

    branch = current_branch()
    for sub, args in git_subcommands(cmd):
        if sub == "push":
            tokens = re.findall(r"[\w./-]+", args)
            targets = {t.removeprefix("refs/heads/") for t in tokens} & PROTECTED
            positional = [a for a in args.split() if not a.startswith("-")]
            if targets or (branch in PROTECTED and len(positional) <= 1):
                block("push directo a main/develop. Abre un PR desde tu rama.")
        if sub == "merge" and branch in PROTECTED:
            block(f"merge directo sobre {branch}. Se integra por PR.")
        if sub == "commit":
            if branch in PROTECTED:
                block(f"commit directo sobre {branch}. Crea una rama feat/... primero.")
            ruff_autofix(all_tracked=bool(re.search(r"\s(-a|--all|-\w*a\w*)\b", args)))


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    if tool in FILE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if is_secret_path(path):
            block(f"acceso a {path} no permitido.")
    elif tool in SHELL_TOOLS:
        check_bash(inp.get("command", ""))
    elif tool in {"Grep", "Glob"}:
        target = f"{inp.get('path', '')} {inp.get('glob', '')} {inp.get('pattern', '')}"
        if ENV_IN_TEXT.search(target):
            block("búsqueda sobre .env no permitida.")


if __name__ == "__main__":
    main()
