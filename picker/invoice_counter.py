import sqlite3
from pathlib import Path

from picker.config import INVOICE_DB_PATH


class InvoiceCounterError(RuntimeError):
    """Raised when a new invoice ID cannot be reserved safely."""


def reserve_invoice_id(db_path: str | Path | None = None) -> str:
    """Atomically reserve and return the next invoice ID."""
    path = Path(db_path) if db_path is not None else INVOICE_DB_PATH
    connection = None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_counter (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                next_invoice_number INTEGER NOT NULL CHECK (next_invoice_number >= 1)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO invoice_counter (singleton, next_invoice_number)
            VALUES (1, 1)
            """
        )
        row = connection.execute(
            "SELECT next_invoice_number FROM invoice_counter WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Invoice counter row is missing")

        invoice_number = int(row[0])
        connection.execute(
            """
            UPDATE invoice_counter
            SET next_invoice_number = ?
            WHERE singleton = 1
            """,
            (invoice_number + 1,),
        )
        connection.commit()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
        raise InvoiceCounterError(f"Could not reserve an invoice ID from {path}") from exc
    finally:
        if connection is not None:
            connection.close()

    return f"{invoice_number:04d}"


def ensure_invoice_id(payload: dict, db_path: str | Path | None = None) -> str:
    """Assign an invoice ID once, retaining it for webhook retries."""
    invoice_details = payload.setdefault("invoice_details", {})
    existing_invoice_id = invoice_details.get("invoice_id")
    if existing_invoice_id:
        return str(existing_invoice_id)

    invoice_id = reserve_invoice_id(db_path)
    invoice_details["invoice_id"] = invoice_id
    return invoice_id
