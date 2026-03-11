import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_codex_slack_env.py"
SPEC = importlib.util.spec_from_file_location("bootstrap_codex_slack_env", MODULE_PATH)
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(BOOTSTRAP)

build_env = BOOTSTRAP.build_env
default_database_url = BOOTSTRAP.default_database_url


def make_slack_env():
    return {
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "SLACK_TEAM_ID": "T12345",
    }


def test_build_env_uses_absolute_sqlite_url_based_on_output_path(tmp_path):
    output_path = tmp_path / "config" / ".env"
    values = build_env({}, make_slack_env(), force=False, output_path=output_path)

    assert values["DATABASE_URL"] == default_database_url(output_path)
    assert values["DATABASE_URL"].startswith("sqlite+aiosqlite:////")


def test_build_env_preserves_existing_database_url_without_force(tmp_path):
    output_path = tmp_path / ".env"
    values = build_env(
        {"DATABASE_URL": "postgresql+asyncpg://user:pass@db/service"},
        make_slack_env(),
        force=False,
        output_path=output_path,
    )

    assert values["DATABASE_URL"] == "postgresql+asyncpg://user:pass@db/service"


def test_build_env_replaces_existing_database_url_when_force_is_enabled(tmp_path):
    output_path = tmp_path / ".env"
    values = build_env(
        {"DATABASE_URL": "sqlite+aiosqlite:///./legacy.db"},
        make_slack_env(),
        force=True,
        output_path=output_path,
    )

    assert values["DATABASE_URL"] == default_database_url(output_path)
