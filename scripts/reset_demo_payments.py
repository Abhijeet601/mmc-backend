from __future__ import annotations

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import engine
from app.migrations import migrate_payment_gateway_columns, purge_legacy_payment_records


logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


def main() -> None:
    migrate_payment_gateway_columns(engine)
    purge_legacy_payment_records(engine)
    print("Demo payment reset complete.")


if __name__ == "__main__":
    main()
