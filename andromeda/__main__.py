"""Local operator entry point. API startup never implicitly changes research data."""

import argparse
import os
import sys

from sqlalchemy.exc import SQLAlchemyError

from .database import cash_cents, database_path, make_engine, migrate
from .storage import evaluate_persisted, ingest


def main() -> int:
    parser = argparse.ArgumentParser(description="Andromeda synthetic research runtime")
    parser.add_argument("command", choices=["migrate", "ingest", "evaluate", "serve"])
    args = parser.parse_args()
    path = database_path()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("andromeda.api:app", host="127.0.0.1", port=8000)
        return 0
    try:
        if args.command == "migrate":
            migrate(path)
            print(f"Database migrated at {path}")
        else:
            engine = make_engine(path)
            try:
                if args.command == "ingest":
                    print(
                        ingest(engine, cash_cents(os.getenv("ANDROMEDA_STARTING_CASH", "1000.00")))
                    )
                else:
                    print(evaluate_persisted(engine))
            finally:
                engine.dispose()
    except (ValueError, RuntimeError, SQLAlchemyError, OSError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
