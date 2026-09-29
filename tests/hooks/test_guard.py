"""Tests de .claude/hooks/guard.py (git_subcommands, check_bash, main)."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

GUARD_PATH = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("guard", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


@pytest.fixture
def env(monkeypatch):
    """Rama simulada y registro de llamadas a ruff_autofix."""
    state = {"branch": "feat/x", "ruff": []}
    monkeypatch.setattr(guard, "current_branch", lambda: state["branch"])
    monkeypatch.setattr(
        guard, "ruff_autofix", lambda all_tracked: state["ruff"].append(all_tracked)
    )
    return state


def assert_blocked(cmd):
    with pytest.raises(SystemExit) as exc:
        guard.check_bash(cmd)
    assert exc.value.code == 2


# ---------- git_subcommands ----------


@pytest.mark.parametrize(
    "cmd",
    [
        "git push origin main",
        "& git push origin main",
        "git.exe push origin main",
        '& "git.exe" push origin main',
        "echo hi | git push origin main",
        "{ git push origin main }",
        "git -C . push origin main",
        "git push origin `\nmain",
        "git push origin \\\nmain",
        "cd x && git push origin main",
        "$ git push origin main",
        '& "C:\\Program Files\\Git\\bin\\git.exe" push origin main',
        "/usr/bin/git push origin main",
        'git -C "mi dir" push origin main',
        "git --git-dir .git push origin main",
        "git --work-tree=. push origin main",
    ],
)
def test_git_subcommands_detecta_push(cmd):
    subs = guard.git_subcommands(cmd)
    assert [s for s, _ in subs] == ["push"]


def test_git_subcommands_varios_y_mayusculas():
    subs = guard.git_subcommands("git commit -m x; GIT Merge feat/a")
    assert [s for s, _ in subs] == ["commit", "merge"]


@pytest.mark.parametrize("cmd", ["", "ls -la", "git status", "echo git push", "gitx push"])
def test_git_subcommands_ignora_no_relevantes(cmd):
    assert guard.git_subcommands(cmd) == []


# ---------- check_bash: push ----------


@pytest.mark.parametrize(
    "cmd",
    [
        "git push origin main",
        "git push origin develop",
        "& git push origin main",
        "git.exe push origin main",
        "echo hi | git push origin main",
        "{ git push origin develop }",
        "git -C . push origin main",
        "git push origin `\nmain",
        "git push origin HEAD:main",
        "git push origin HEAD:develop",
    ],
)
def test_push_a_rama_protegida_bloqueado(env, cmd):
    assert_blocked(cmd)


def test_push_a_feature_desde_feature_permitido(env):
    guard.check_bash("git push origin feat/x")
    guard.check_bash("git push -u origin feat/x")
    guard.check_bash("git push")  # sin args desde rama feature


def test_push_sin_args_en_develop_bloqueado(env):
    env["branch"] = "develop"
    assert_blocked("git push")


def test_push_sin_args_en_main_bloqueado(env):
    env["branch"] = "main"
    assert_blocked("git push")


# ---------- check_bash: merge / commit ----------


def test_merge_en_protegida_bloqueado(env):
    env["branch"] = "main"
    assert_blocked("git merge feat/x")


def test_merge_en_feature_permitido(env):
    guard.check_bash("git merge origin/develop")


def test_commit_en_develop_bloqueado(env):
    env["branch"] = "develop"
    assert_blocked('git commit -m "x"')
    assert env["ruff"] == []


def test_commit_en_feature_llama_ruff(env):
    guard.check_bash('git commit -m "x"')
    assert env["ruff"] == [False]


def test_commit_con_all_pasa_all_tracked(env):
    guard.check_bash('git commit -am "x"')
    guard.check_bash('git commit --all -m "x"')
    assert env["ruff"] == [True, True]


# ---------- check_bash: secretos ----------


def test_ruta_pdf_con_barra_invertida_bloqueada(env):
    assert_blocked("type " + "docs" + "\\" + "pdf" + "\\x.pdf")


def test_ruta_pdf_con_barra_normal_bloqueada(env):
    assert_blocked("cat " + "docs" + "/" + "pdf/x.pdf")


def test_env_bloqueado_y_example_permitido(env):
    assert_blocked("cat ." + "env")
    guard.check_bash("cat ." + "env.example")


@pytest.mark.parametrize("cmd", ["ls -la", "uv run pytest -q", "echo hola", ""])
def test_no_git_no_bloquea(env, cmd):
    guard.check_bash(cmd)
    assert env["ruff"] == []


# ---------- main ----------


def run_main(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    guard.main()


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_main_herramientas_shell_pasan_por_check_bash(env, monkeypatch, tool):
    payload = {"tool_name": tool, "tool_input": {"command": "& git push origin main"}}
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, payload)
    assert exc.value.code == 2


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_main_shell_comando_inofensivo(env, monkeypatch, tool):
    run_main(monkeypatch, {"tool_name": tool, "tool_input": {"command": "ls"}})


def test_main_powershell_commit_llama_ruff(env, monkeypatch):
    payload = {
        "tool_name": "PowerShell",
        "tool_input": {"command": 'git.exe commit -m "x"'},
    }
    run_main(monkeypatch, payload)
    assert env["ruff"] == [False]


def test_main_archivo_secreto_bloqueado(env, monkeypatch):
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/repo/." + "env"}}
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, payload)
    assert exc.value.code == 2


def test_main_herramienta_desconocida_y_sin_input(env, monkeypatch):
    run_main(monkeypatch, {"tool_name": "Otra", "tool_input": None})
    run_main(monkeypatch, {"tool_name": "PowerShell"})
