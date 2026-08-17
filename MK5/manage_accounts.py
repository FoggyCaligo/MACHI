from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from MK5.app.accounts import AccountStore
from MK5.core.graph.repository import GraphRepository
from MK5.core.graph.service import GraphMemoryService


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect MK5 .env accounts or purge one account's graph memory.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List configured roles and graph identities without revealing login IDs.")

    purge_parser = subparsers.add_parser("purge-memory", help="Delete graph memory for one allowed login ID.")
    purge_parser.add_argument("--login-id", help="Allowed login ID. Omit to enter it without terminal echo.")

    args = parser.parse_args()
    store = AccountStore()
    if args.command == "list":
        print(json.dumps(store.list_accounts(), ensure_ascii=False, indent=2))
        return

    login_id = args.login_id or getpass.getpass("Login ID whose graph memory will be deleted: ")
    account = store.authenticate(login_id)
    if account is None:
        raise SystemExit("The login ID is not present in MK5_ALLOWED_LOGIN_IDS.")
    confirmation = input(f"Type DELETE {account.graph_user_id} to erase this graph memory: ")
    if confirmation != f"DELETE {account.graph_user_id}":
        raise SystemExit("Cancelled; confirmation did not match.")

    repo = GraphRepository()
    try:
        result = GraphMemoryService(repo).delete_user_memory(account.graph_user_id)
    finally:
        repo.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
