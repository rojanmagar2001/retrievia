from __future__ import annotations

import argparse

from alembic import command
from alembic.config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Alembic migrations.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade DB schema")
    upgrade_parser.add_argument("revision", nargs="?", default="head")

    downgrade_parser = subparsers.add_parser("downgrade", help="Downgrade DB schema")
    downgrade_parser.add_argument("revision", nargs="?", default="-1")

    subparsers.add_parser("current", help="Show current DB revision")

    args = parser.parse_args()
    cfg = Config("alembic.ini")

    if args.action == "upgrade":
        command.upgrade(cfg, args.revision)
    elif args.action == "downgrade":
        command.downgrade(cfg, args.revision)
    elif args.action == "current":
        command.current(cfg, verbose=True)


if __name__ == "__main__":
    main()
