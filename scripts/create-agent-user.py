#!/usr/bin/env python3
"""Create (or reset) the NousViz service account the Hermes plugin logs in with.

Run this ON the NousViz server, with the instance's own venv so bcrypt/psycopg2
match the app:

    sudo /opt/nousviz/.venv/bin/python create-agent-user.py \
        --email hermes-agent@example.com

It reads Postgres connection settings from the instance .env (default
/opt/nousviz/.env, override with --env-file), creates the user with the
analyst role (enough for nousviz_query / dashboards / alerts), generates a
password if you don't pass one, and prints it ONCE. Put that password in
~/.hermes/.env as NOUSVIZ_PASSWORD on the machine running Hermes.

Why this exists: NousViz's invite flow delivers the invite link only by
email, which doesn't work for service accounts without a mailbox (see
nousviz-docs issue about showing invite links to admins).
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

try:
    import bcrypt
    import psycopg2
except ImportError as e:
    sys.exit(f"Missing dependency ({e.name}). Run with the NousViz instance venv, "
             "e.g. /opt/nousviz/.venv/bin/python")


def read_env(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Hermes Agent")
    p.add_argument("--role", default="analyst",
                   choices=["viewer", "analyst", "admin"],
                   help="analyst (default) is enough for the Hermes plugin")
    p.add_argument("--password", default=None,
                   help="omit to generate one (printed once)")
    p.add_argument("--env-file", default="/opt/nousviz/.env")
    args = p.parse_args()

    env = read_env(Path(args.env_file))
    conn = psycopg2.connect(
        host=env.get("POSTGRES_HOST", "localhost"),
        port=int(env.get("POSTGRES_PORT", "5432")),
        user=env.get("POSTGRES_USER", "nousviz"),
        password=env.get("POSTGRES_PASSWORD") or None,
        dbname=env.get("POSTGRES_DB", "nousviz"),
    )
    conn.autocommit = True
    cur = conn.cursor()

    password = args.password or secrets.token_urlsafe(18)
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    cur.execute("SELECT id FROM users WHERE email = %s", (args.email.lower(),))
    if cur.fetchone():
        cur.execute(
            "UPDATE users SET password_hash = %s, role = %s, is_active = true "
            "WHERE email = %s", (pw_hash, args.role, args.email.lower()))
        action = "updated (password reset)"
    else:
        cur.execute(
            "INSERT INTO users (email, name, role, password_hash) "
            "VALUES (%s, %s, %s, %s)",
            (args.email.lower(), args.name, args.role, pw_hash))
        action = "created"

    print(f"User {args.email} {action} with role {args.role}.")
    if not args.password:
        print(f"\nGenerated password (shown once, store it now):\n  {password}\n")
    print("On the Hermes machine, add to ~/.hermes/.env:\n"
          f"  NOUSVIZ_PASSWORD={'<the password above>' if not args.password else '<your password>'}")


if __name__ == "__main__":
    main()
