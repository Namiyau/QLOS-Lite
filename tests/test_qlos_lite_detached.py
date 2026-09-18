import inspect
import os
import sys


def test_qlos_lite_imports_as_top_level_package_without_app_config():
    sys.modules.pop("app.config", None)

    from qlos_lite.config import load_local_secret_env

    source = inspect.getsource(load_local_secret_env)
    assert "app.config" not in source
    assert "load_local_secret_env" in source


def test_qlos_lite_local_env_loader_reads_secret_file(monkeypatch, tmp_path):
    from qlos_lite.config import load_local_secret_env

    secret_file = tmp_path / "secrets.local.env"
    secret_file.write_text(
        "\n".join(
            [
                "QLOS_OWNER_QQ_ID=1000000001",
                "QLOS_HERMES_API_KEY='file-secret'",
                "# comment",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("QLOS_OWNER_QQ_ID", raising=False)
    monkeypatch.setenv("QLOS_HERMES_API_KEY", "already-set")

    load_local_secret_env(secret_file)

    assert os.environ["QLOS_OWNER_QQ_ID"] == "1000000001"
    assert os.environ["QLOS_HERMES_API_KEY"] == "already-set"

