import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType

from click.testing import CliRunner
from flask import Flask
from flask.cli import cli


BFF = Path(__file__).resolve().parents[1]
LAUNCHER = BFF / "scripts" / "run_local.sh"


def test_launcher_resolves_paths_without_sourcing_or_overriding_environment():
    assert LAUNCHER.is_file()
    with TemporaryDirectory(prefix=".startup-test-", dir=BFF) as directory:
        root = Path(directory) / "synthetic workspace"
        scripts = root / "bgg-shop-bff" / "scripts"
        scripts.mkdir(parents=True)
        launcher = scripts / "run_local.sh"
        shutil.copy2(LAUNCHER, launcher)
        python = root / "bgg-shop-bff" / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text(
            '#!/bin/bash\nprintf "%s\\n" "$PWD" "$FLASK_SKIP_DOTENV" '
            '"$CHAT_EMBEDDING_MODEL" "$@"\n',
            encoding="utf-8",
        )
        python.chmod(0o755)
        marker = root / "must-not-exist"
        (root / ".env").write_text(
            f"CHAT_EMBEDDING_MODEL=synthetic-file-model\n"
            f"touch '{marker}'\n",
            encoding="utf-8",
        )
        elsewhere = root / "unrelated working directory"
        elsewhere.mkdir()
        environment = os.environ.copy()
        environment["CHAT_EMBEDDING_MODEL"] = "synthetic-exported-model"
        environment["FLASK_SKIP_DOTENV"] = "0"
        result = subprocess.run(
            ["bash", str(launcher)],
            cwd=elsewhere,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.splitlines() == [
            str(root / "bgg-shop-bff"),
            "1",
            "synthetic-exported-model",
            "-m",
            "flask",
            "--env-file",
            str(root / ".env"),
            "--app",
            "app:app",
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            "5000",
        ]
        assert not marker.exists()


def test_flask_explicit_env_file_preserves_exports_and_skips_default_files(monkeypatch):
    with TemporaryDirectory(prefix=".dotenv-test-", dir=BFF) as directory:
        root = Path(directory)
        selected = root / "synthetic.env"
        selected.write_text(
            "STARTUP_TEST_EXPORTED=file-value\nSTARTUP_TEST_FILE=file-only\n",
            encoding="utf-8",
        )
        (root / ".env").write_text(
            "STARTUP_TEST_DEFAULT=must-not-load\n", encoding="utf-8"
        )
        (root / ".flaskenv").write_text(
            "STARTUP_TEST_DEFAULT=must-not-load\n", encoding="utf-8"
        )
        monkeypatch.chdir(root)
        monkeypatch.setenv("FLASK_SKIP_DOTENV", "1")
        monkeypatch.setenv("STARTUP_TEST_EXPORTED", "exported-value")
        monkeypatch.delenv("STARTUP_TEST_FILE", raising=False)
        monkeypatch.delenv("STARTUP_TEST_DEFAULT", raising=False)
        module = ModuleType("_synthetic_startup_app")
        module.app = Flask(module.__name__)

        @module.app.cli.command("show-config")
        def show_config():
            print(os.environ["STARTUP_TEST_EXPORTED"])
            print(os.environ["STARTUP_TEST_FILE"])
            print(os.environ.get("STARTUP_TEST_DEFAULT", "absent"))

        monkeypatch.setitem(sys.modules, module.__name__, module)
        result = CliRunner().invoke(
            cli,
            [
                "--env-file", str(selected),
                "--app", f"{module.__name__}:app",
                "show-config",
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.output.splitlines() == ["exported-value", "file-only", "absent"]
