from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from .config import ConfigError, load_config
from .logging_setup import configure_logging
from .service import AutoReplyService
from .storage import Database, Repository
from .wechat import HttpWeChatBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Windows WeChat message ingestion service")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="YAML configuration path (default: config.yaml)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        logger = configure_logging(config.logging)
    except (ConfigError, OSError, ValueError) as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("unable to start: %s", exc)
        return 2

    logger.info("loading application database: %s", config.database.path)
    database = Database(config.database.path)
    repository = Repository(database)
    bridge = HttpWeChatBridge(
        config.bridge.url,
        request_timeout_seconds=config.bridge.request_timeout_seconds,
    )
    service = AutoReplyService(
        bridge=bridge,
        repository=repository,
        poll_timeout_seconds=config.bridge.poll_timeout_seconds,
        poll_limit=config.bridge.poll_limit,
        retry_delay_seconds=config.bridge.retry_delay_seconds,
        logger=logger,
    )

    try:
        service.run_forever()
    except KeyboardInterrupt:
        logger.info("shutdown requested")
    except Exception:
        logger.exception("fatal service error")
        return 1
    return 0
