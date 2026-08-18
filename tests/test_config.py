from __future__ import annotations

from wechat_auto_reply.config import load_config


def test_config_resolves_paths_relative_to_config_file(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
app: {name: test}
bridge:
  url: http://127.0.0.1:8765
  poll_timeout_seconds: 30
  poll_limit: 1
  request_timeout_seconds: 10
  retry_delay_seconds: 5
database: {path: ./data/app.sqlite3}
logging:
  level: INFO
  file_path: ./data/logs/app.log
  max_bytes: 1000
  backup_count: 1
context: {recent_message_limit: 20}
llm:
  enabled: false
  base_url: http://127.0.0.1:8080/v1
  model: qwen3.5-9b
  timeout_seconds: 120
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.database.path == (tmp_path / "data/app.sqlite3").resolve()
    assert config.logging.file_path == (tmp_path / "data/logs/app.log").resolve()
    assert config.llm.enabled is False
