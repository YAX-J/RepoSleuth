"""仓库分析基础能力的离线回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from reposleuth_toolkit import ingest_repo, scan_risks


@pytest.mark.parametrize("filename", [".env", ".env.local", ".env.production", ".env.backup.txt"])
def test_ingest_excludes_environment_secrets(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_text("PASSWORD=synthetic-env-sensitive-value\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Public documentation", encoding="utf-8")
    result = ingest_repo(tmp_path)
    assert "synthetic-env-sensitive-value" not in result.content_text
    assert "Public documentation" in result.content_text


def test_ingest_redacts_code_credentials_and_private_keys(tmp_path: Path) -> None:
    (tmp_path / "settings.py").write_text(
        'API_KEY = "synthetic-code-sensitive-value"\n'
        'CONFIG = {"DATABASE_PASSWORD": "synthetic-dict-sensitive-value"}\n',
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text(
        "-----BEGIN PRIVATE KEY-----\nsynthetic-pem-sensitive-value\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    result = ingest_repo(tmp_path)
    assert "API_KEY" in result.content_text
    assert "synthetic-code-sensitive-value" not in result.content_text
    assert "synthetic-dict-sensitive-value" not in result.content_text
    assert "synthetic-pem-sensitive-value" not in result.content_text
    assert scan_risks(tmp_path).summary()["critical"] >= 1
    assert "synthetic-code-sensitive-value" in (tmp_path / "settings.py").read_text(encoding="utf-8")


def test_ingest_directory_tree_obeys_small_budget(tmp_path: Path) -> None:
    (tmp_path / "a_long_filename.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = ingest_repo(tmp_path, max_total_chars=5)
    assert result.total_chars <= 5
    assert "a_long_filename.py" in result.truncated_files


def test_ingest_redacts_multiline_secret_literal(tmp_path: Path) -> None:
    (tmp_path / "settings.py").write_text(
        'API_KEY = """synthetic-multiline-sensitive-value\ncontinued-secret"""\n',
        encoding="utf-8",
    )
    result = ingest_repo(tmp_path)
    assert "synthetic-multiline-sensitive-value" not in result.content_text
    assert "continued-secret" not in result.content_text


def test_ingest_redacts_unquoted_yaml_secret(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("password: synthetic-yaml-sensitive-value\n", encoding="utf-8")
    assert "synthetic-yaml-sensitive-value" not in ingest_repo(tmp_path).content_text
