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
    state = {"branch": "feat/x", "ruff": [], "paths": []}

    def fake_ruff_autofix(all_tracked, pathspecs=None):
        state["ruff"].append(all_tracked)
        state["paths"].append(pathspecs or [])

    monkeypatch.setattr(guard, "current_branch", lambda: state["branch"])
    monkeypatch.setattr(guard, "ruff_autofix", fake_ruff_autofix)
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


@pytest.mark.parametrize(
    "cmd", ["", "ls -la", "git status", "echo git push", "gitx push"]
)
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
        "git push origin HEAD:refs/heads/main",
        "git push origin refs/heads/develop",
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


@pytest.mark.parametrize(
    "cmd",
    [
        "git push origin HEAD",
        "git push -u origin HEAD",
        "git push origin @",
        "git push origin 2>&1",
        "git push origin > out.txt",
    ],
)
def test_push_de_la_rama_actual_en_develop_bloqueado(env, cmd):
    env["branch"] = "develop"
    assert_blocked(cmd)


def test_push_head_a_feature_permitido(env):
    guard.check_bash("git push -u origin HEAD")
    env["branch"] = "develop"
    guard.check_bash("git push origin HEAD:feat/x")


# ---------- check_bash: merge / commit ----------


def test_merge_en_protegida_bloqueado(env):
    env["branch"] = "main"
    assert_blocked("git merge feat/x")


def test_merge_en_feature_permitido(env):
    guard.check_bash("git merge origin/develop")


def test_merge_base_y_commit_tree_no_son_merge_ni_commit(env):
    assert guard.git_subcommands("git merge-base develop HEAD") == []
    assert guard.git_subcommands("git commit-tree abc") == []
    env["branch"] = "develop"
    guard.check_bash("git merge-base develop HEAD")


def test_parentesis_en_el_mensaje_no_cortan_el_commit(env):
    guard.check_bash('git commit -m "feat(etl): x" -a')
    assert env["ruff"] == [True]


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


def test_add_en_el_mismo_comando_pasa_pathspecs(env):
    guard.check_bash('git add a.py "dir con espacio/b.py" && git commit -m "x"')
    assert env["paths"] == [["a.py", "dir con espacio/b.py"]]


def test_add_all_sin_rutas_equivale_a_todo(env):
    guard.check_bash('git add -A; git commit -m "x"')
    assert env["paths"] == [["."]]


def test_commit_sin_add_no_pasa_pathspecs(env):
    guard.check_bash('git commit -m "x"')
    assert env["paths"] == [[]]


def test_add_sin_commit_no_llama_ruff(env):
    guard.check_bash("git add a.py")
    assert env["ruff"] == []


# ---------- check_bash: secretos ----------


def test_ruta_pdf_con_barra_invertida_bloqueada(env):
    assert_blocked("type " + "docs" + "\\" + "pdf" + "\\x.pdf")


def test_ruta_pdf_con_barra_normal_bloqueada(env):
    assert_blocked("cat " + "docs" + "/" + "pdf/x.pdf")


def test_env_bloqueado_y_example_permitido(env):
    assert_blocked("cat ." + "env")
    guard.check_bash("cat ." + "env.example")


# ---------- check_bash: S3 ----------


@pytest.mark.parametrize(
    "cmd",
    [
        "aws s3 ls s3://bucket/data/",
        "aws s3 sync s3://bucket/data/ ./data/",
        "aws s3 cp s3://bucket/data/ . --recursive",
        "aws s3api list-objects-v2 --bucket b",
        "AWS S3 ls",
        "& aws.exe s3 ls",
        "aws.cmd s3 ls",
        '& "C:\\Program Files\\Amazon\\AWSCLIV2\\aws.exe" s3 ls',
        "cd x && aws s3 ls",
        "echo hi | aws s3 ls",
        "aws --profile x s3 sync s3://b/ ./d/",
        "aws --region us-east-1 s3 ls",
        "aws --no-sign-request s3 cp s3://b/k .",
        "aws --debug s3api list-objects-v2 --bucket b",
    ],
)
def test_cli_aws_s3_bloqueada(env, cmd):
    assert_blocked(cmd)


@pytest.mark.parametrize(
    "cmd",
    ["aws --version", "aws sts get-caller-identity", "echo laws s3", "uv run aws_s3x"],
)
def test_otros_comandos_aws_permitidos(env, cmd):
    guard.check_bash(cmd)


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
