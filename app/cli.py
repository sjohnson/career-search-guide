"""CLI utilities for local operations."""

import argparse
import getpass
import sys

from app.database import SessionLocal
from app.services.auth import create_user, registration_allowed


def _create_user_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        if not registration_allowed(db, allow_registration=args.allow_existing):
            print(
                "A user already exists. Re-run with --allow-existing to add another account.",
                file=sys.stderr,
            )
            return 1

        email = args.email
        if not email:
            email = input("Email: ").strip()
        password = args.password
        if not password:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Passwords do not match.", file=sys.stderr)
                return 1

        user = create_user(db, email, password)
        print(f"Created user {user.email} (id={user.id}).")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-user", help="Create a user account")
    create_parser.add_argument("--email", help="Account email")
    create_parser.add_argument("--password", help="Account password (omit to prompt)")
    create_parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow creating a user when accounts already exist",
    )
    create_parser.set_defaults(func=_create_user_command)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
