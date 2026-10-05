"""Create an operator account without public signup or printing a password."""

import argparse
import getpass
import os

from backend.auth.models import Signup
from backend.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Tracy owner")
    args = parser.parse_args()
    password = os.environ.get("TRACY_BOOTSTRAP_PASSWORD") or getpass.getpass("Owner password: ")
    app = create_app()
    user = app.state.auth.register(Signup(email=args.email, name=args.name, password=password))
    print("Created owner account:", user["email"])


if __name__ == "__main__":
    main()
