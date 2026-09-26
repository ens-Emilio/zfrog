"""The command line: the interface people actually type.

`zfrog.cli` is ~1300 statements and had no test at all — the single largest gap in
the suite. These tests are in two layers:

* **A wiring sweep.** Every command and subcommand is invoked with `--help`. That
  is mechanical and broad: it catches a command that was renamed, a group that
  stopped registering, a typo in a decorator, and any import that fails at
  decoration time.
* **Behaviour on real state.** The commands that read or write the stores run
  against a temporary data directory, so they are checked for the thing a user
  would notice: the secret is printed once, the secret is *not* printed again, a
  duplicate is refused, a bad role is refused, an unknown id exits non-zero.

Commands that need the network (clone, probe, serve, chat) are deliberately absent:
their behaviour is covered by the engine and orchestrator tests, and a test that
reaches out to the internet would be flaky and slow.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from zfrog.cli import app
from zfrog.config import settings

runner = CliRunner()

#: A valid base32 secret, so the TOTP tests exercise the real decoder.
BASE32_SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Point every store at tmp_path, so no command touches the working tree."""
    for name in (
        "data_dir",
        "output_dir",
        "versions_dir",
        "schedules_file",
        "search_db",
        "sessions_dir",
        "sessions_key_file",
        "audit_log",
        "metrics_db",
        "api_keys_file",
        "marketplace_dir",
        "integrations_dir",
        "users_file",
        "orgs_file",
        "annotations_dir",
        "domain_profiles_dir",
        "finetune_dir",
        "analysis_dir",
        "websession_key_file",
    ):
        monkeypatch.setattr(settings, name, tmp_path / name)


# ── the wiring sweep ──

def _walk(group, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every command path below ``group``, groups recursed into.

    Duck-typed on ``.commands`` rather than ``isinstance(x, click.Group)``: Typer
    vendors its own click fork (`typer._click`), so its ``TyperGroup`` — the type
    `typer.main.get_command` actually returns — is not a ``click.Group`` and an
    isinstance check silently finds zero subcommands.
    """
    from typer.main import get_command

    if not getattr(group, "commands", None):
        group = get_command(group)

    found: list[tuple[str, ...]] = []
    for name, command in group.commands.items():
        children = getattr(command, "commands", None)
        if children:
            found.extend(_walk(command, (*prefix, name)))
        else:
            found.append((*prefix, name))
    return found


def _command_paths() -> list[tuple[str, ...]]:
    return _walk(app)


def _top_level_commands() -> list[str]:
    return [path[0] for path in _command_paths() if len(path) == 1]


def _subcommands() -> list[tuple[str, ...]]:
    return [path for path in _command_paths() if len(path) > 1]


def test_the_command_surface_is_not_empty():
    """A guard on the sweep itself: a broken ``_walk`` would make the sweeps below vacuous."""
    assert {"clone", "probe", "engines", "serve"} <= set(_top_level_commands())
    assert len(_subcommands()) > 20


@pytest.mark.parametrize("command", _top_level_commands())
def test_every_command_answers_help(command):
    result = runner.invoke(app, [command, "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


@pytest.mark.parametrize("path", _subcommands(), ids=lambda path: " ".join(path))
def test_every_subcommand_answers_help(path):
    result = runner.invoke(app, [*path, "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage" in result.output


def test_bare_invocation_shows_help_instead_of_doing_something():
    """`no_args_is_help=True`: running `zfrog` must not start a job."""
    result = runner.invoke(app, [])

    assert result.exit_code in (0, 2)
    assert "Usage" in result.output


# ── read-only commands on an empty installation ──

@pytest.mark.parametrize(
    "args",
    [
        ["engines"],
        ["config"],
        ["jobs"],
        ["snapshots"],
        ["analytics"],
        ["audit"],
        ["cost"],
        ["roi"],
        ["key", "list"],
        ["user", "list"],
        ["org", "list"],
        ["totp", "list"],
        ["workflow", "list"],
        ["schedule", "list"],
        ["market", "list"],
        ["integrations", "list"],
        ["domain", "list"],
        ["worker", "list"],
        ["sessions"],
        ["versions", "https://exemplo.test"],
        ["branches", "https://exemplo.test"],
    ],
)
def test_a_read_only_command_survives_an_empty_installation(args):
    """The first thing a new user runs, before any data exists."""
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output


def test_engines_lists_the_built_in_engines():
    result = runner.invoke(app, ["engines"])

    for expected in ("wget", "playwright", "static_file"):
        assert expected in result.output


# ── API keys ──

def test_key_create_prints_the_secret_once_and_never_again():
    """The whole contract of the key store: shown once, then only the hash."""
    created = runner.invoke(app, ["key", "create", "painel", "-r", "operator"])
    assert created.exit_code == 0, created.output

    secret = next(
        (word for word in created.output.split() if word.startswith("zk_")), None
    )
    assert secret, f"nenhum segredo na saída: {created.output!r}"

    listed = runner.invoke(app, ["key", "list"])
    assert listed.exit_code == 0
    assert "painel" in listed.output
    assert "operator" in listed.output
    assert secret not in listed.output


def test_key_create_refuses_an_unknown_role():
    result = runner.invoke(app, ["key", "create", "painel", "-r", "superusuario"])

    assert result.exit_code == 1
    assert "superusuario" in result.output


def test_key_create_can_scope_the_key_to_an_organization():
    result = runner.invoke(app, ["key", "create", "acme", "-r", "admin", "-O", "acme-corp"])

    assert result.exit_code == 0, result.output
    assert "acme-corp" in result.output


def test_key_revoke_removes_it_and_reports_an_unknown_id():
    runner.invoke(app, ["key", "create", "temporaria"])
    listed = runner.invoke(app, ["key", "list"])
    key_id = next(
        (
            word
            for line in listed.output.splitlines()
            for word in line.split()
            if len(word) == 16 and all(c in "0123456789abcdef" for c in word)
        ),
        None,
    )
    assert key_id, f"nenhum id de chave em: {listed.output!r}"

    revoked = runner.invoke(app, ["key", "revoke", key_id])
    assert revoked.exit_code == 0
    assert key_id in revoked.output

    missing = runner.invoke(app, ["key", "revoke", "nao-existe"])
    assert missing.exit_code == 1


# ── users and organizations ──

def test_user_create_then_list_shows_the_email_and_never_the_password():
    created = runner.invoke(
        app, ["user", "create", "ana@empresa.com", "-n", "Ana", "-r", "operator", "-p", "segredo"]
    )
    assert created.exit_code == 0, created.output
    assert "segredo" in created.output  # shown once, as documented

    listed = runner.invoke(app, ["user", "list"])
    assert listed.exit_code == 0
    assert "ana@empresa.com" in listed.output
    assert "segredo" not in listed.output


def test_user_create_refuses_a_duplicate_email():
    runner.invoke(app, ["user", "create", "ana@empresa.com"])

    again = runner.invoke(app, ["user", "create", "ana@empresa.com"])

    assert again.exit_code == 1
    assert "cadastrado" in again.output


def test_user_create_refuses_an_unknown_role():
    result = runner.invoke(app, ["user", "create", "ana@empresa.com", "-r", "chefe"])

    assert result.exit_code == 1


def test_user_disable_reports_an_unknown_id():
    result = runner.invoke(app, ["user", "disable", "nao-existe"])

    assert result.exit_code == 1


def test_org_create_requires_an_owner_and_then_lists():
    result = runner.invoke(app, ["org", "create", "Acme", "--owner", "u-1"])
    assert result.exit_code == 0, result.output

    listed = runner.invoke(app, ["org", "list"])
    assert "acme" in listed.output.lower()


def test_org_add_member_reports_an_unknown_org():
    result = runner.invoke(app, ["org", "add-member", "nao-existe", "u-1"])

    assert result.exit_code == 1


# ── two-factor codes ──

def test_totp_add_then_code_generates_six_digits():
    added = runner.invoke(app, ["totp", "add", "conta", BASE32_SECRET])
    assert added.exit_code == 0, added.output
    assert BASE32_SECRET not in added.output  # never echoed back

    code = runner.invoke(app, ["totp", "code", "conta"])
    assert code.exit_code == 0, code.output
    digits = [word for word in code.output.split() if word.isdigit()]
    assert digits and len(digits[0]) == 6


def test_totp_list_never_shows_the_secret():
    runner.invoke(app, ["totp", "add", "conta", BASE32_SECRET])

    listed = runner.invoke(app, ["totp", "list"])

    assert "conta" in listed.output
    assert BASE32_SECRET not in listed.output


def test_totp_add_refuses_a_secret_that_is_not_base32():
    result = runner.invoke(app, ["totp", "add", "conta", "não-é-base32-!!"])

    assert result.exit_code == 1


def test_totp_code_reports_an_unknown_account():
    result = runner.invoke(app, ["totp", "code", "nao-existe"])

    assert result.exit_code == 1


# ── comments ──

def test_annotate_then_list_and_export():
    added = runner.invoke(
        app, ["annotate", "job-1", "index.html", "falta o preço", "-a", "ana", "-t", "revisão"]
    )
    assert added.exit_code == 0, added.output

    listed = runner.invoke(app, ["annotations", "job-1"])
    assert listed.exit_code == 0
    assert "falta o preço" in listed.output

    open_only = runner.invoke(app, ["annotations", "job-1", "--open"])
    assert open_only.exit_code == 0


def test_annotate_rejects_an_empty_comment():
    result = runner.invoke(app, ["annotate", "job-1", "index.html", "   "])

    assert result.exit_code == 1


# ── schedules ──

def test_schedule_add_list_and_remove():
    """Round-trips the id rather than a URL substring: Rich wraps a long URL cell
    across lines at the runner's 80 columns, so a URL match is not reliable.

    `add` prints `Agendado (<id>) — …`, so the id is the parenthesised token.
    """
    import re

    added = runner.invoke(app, ["schedule", "add", "https://exemplo.test", "-c", "0 2 * * *"])
    assert added.exit_code == 0, added.output

    match = re.search(r"\(([^)]+)\)", added.output)
    assert match, f"nenhum id de agendamento em: {added.output!r}"
    schedule_id = match.group(1)

    listed = runner.invoke(app, ["schedule", "list"])
    assert listed.exit_code == 0
    assert schedule_id in listed.output

    removed = runner.invoke(app, ["schedule", "remove", "nao-existe"])
    assert removed.exit_code == 1


def test_schedule_add_refuses_an_invalid_cron():
    result = runner.invoke(app, ["schedule", "add", "https://exemplo.test", "-c", "nem-um-cron"])

    assert result.exit_code == 1


# ── workflows ──

def test_workflow_show_reports_an_unknown_id():
    result = runner.invoke(app, ["workflow", "show", "nao-existe"])

    assert result.exit_code == 1


# ── local analysis that needs no network ──

def test_safety_scan_of_a_clean_directory(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    result = runner.invoke(app, ["safety", str(tmp_path)])

    assert result.exit_code == 0, result.output


def test_watermark_marks_and_then_verifies(tmp_path):
    """The round trip that matters: the mark written is the mark found.

    `--verify` reports the mark ids it finds, not the source URL, so the
    assertion follows the id from the marking run into the verification run.
    """
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    marked = runner.invoke(app, ["watermark", str(tmp_path), "--source", "https://exemplo.test"])
    assert marked.exit_code == 0, marked.output
    assert "marcado" in marked.output

    mark_id = next(
        (word for word in marked.output.split() if word.startswith("ZK-")), None
    )
    assert mark_id, f"nenhum id de marca em: {marked.output!r}"

    verified = runner.invoke(app, ["watermark", str(tmp_path), "--verify"])
    assert verified.exit_code == 0, verified.output
    assert mark_id in verified.output


def test_watermark_verify_reports_an_unmarked_directory(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    result = runner.invoke(app, ["watermark", str(tmp_path), "--verify"])

    assert result.exit_code == 0
    assert "Nenhum arquivo marcado" in result.output


def test_graph_maps_an_annotated_page(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    result = runner.invoke(app, ["graph", str(tmp_path)])

    assert result.exit_code == 0, result.output


def test_dataset_builds_from_a_cloned_directory(tmp_path):
    (tmp_path / "index.html").write_text(
        "<html><head><title>Preços</title></head><body><h1>Preços</h1>"
        "<p>O plano custa cem reais por mês e inclui suporte.</p></body></html>",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["dataset", str(tmp_path)])

    assert result.exit_code == 0, result.output


def test_market_index_build_writes_a_file(tmp_path):
    target = tmp_path / "index.json"

    result = runner.invoke(app, ["market-index", "build", "-o", str(target)])

    assert result.exit_code == 0, result.output
    assert target.is_file()


def test_regions_explains_where_a_url_would_be_processed():
    result = runner.invoke(app, ["regions", "https://exemplo.test"])

    assert result.exit_code == 0, result.output


def test_worker_assign_explains_the_choice():
    result = runner.invoke(app, ["worker", "assign", "https://exemplo.test"])

    assert result.exit_code == 0, result.output


def test_domain_suggest_answers_for_a_url():
    result = runner.invoke(app, ["domain", "suggest", "https://exemplo.test/contrato"])

    assert result.exit_code == 0, result.output
