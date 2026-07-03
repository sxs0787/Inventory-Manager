"""
database.py
-----------
Handles all SQLite database operations for the inventory app.
Keeping this separate from the UI means the storage logic can be
tested and reused independently of Tkinter.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "inventory.db"


class InventoryDB:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT,
                    quantity INTEGER DEFAULT 0,
                    unit_price REAL DEFAULT 0,
                    supplier TEXT,
                    reorder_level INTEGER DEFAULT 0,
                    last_updated TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    added INTEGER,
                    updated INTEGER,
                    skipped INTEGER,
                    timestamp TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS column_mapping (
                    field_name TEXT PRIMARY KEY,
                    excel_column TEXT
                )
            """)
            conn.commit()

    # ---------- CRUD ----------

    def get_all_products(self, search_term=None):
        query = "SELECT * FROM products"
        params = ()
        if search_term:
            query += " WHERE sku LIKE ? OR name LIKE ? OR category LIKE ? OR supplier LIKE ?"
            like = f"%{search_term}%"
            params = (like, like, like, like)
        query += " ORDER BY name COLLATE NOCASE"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_product(self, product_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            return dict(row) if row else None

    def add_product(self, sku, name, category, quantity, unit_price, supplier, reorder_level):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO products (sku, name, category, quantity, unit_price, supplier, reorder_level, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sku, name, category, quantity, unit_price, supplier, reorder_level,
                  datetime.now().isoformat(timespec="seconds")))
            conn.commit()

    def update_product(self, product_id, sku, name, category, quantity, unit_price, supplier, reorder_level):
        with self._connect() as conn:
            conn.execute("""
                UPDATE products
                SET sku=?, name=?, category=?, quantity=?, unit_price=?, supplier=?, reorder_level=?, last_updated=?
                WHERE id=?
            """, (sku, name, category, quantity, unit_price, supplier, reorder_level,
                  datetime.now().isoformat(timespec="seconds"), product_id))
            conn.commit()

    def delete_product(self, product_id):
        with self._connect() as conn:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()

    def sku_exists(self, sku):
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
            return row["id"] if row else None

    # ---------- Sync (upsert from Excel) ----------

    def upsert_from_excel(self, records):
        """
        records: list of dicts with keys sku, name, category, quantity,
                 unit_price, supplier, reorder_level
        Returns (added_count, updated_count, skipped_count)
        """
        added = 0
        updated = 0
        skipped = 0
        now = datetime.now().isoformat(timespec="seconds")

        with self._connect() as conn:
            for rec in records:
                sku = (rec.get("sku") or "").strip()
                if not sku:
                    skipped += 1
                    continue

                existing = conn.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
                if existing:
                    conn.execute("""
                        UPDATE products
                        SET name=?, category=?, quantity=?, unit_price=?, supplier=?, reorder_level=?, last_updated=?
                        WHERE sku=?
                    """, (rec.get("name", ""), rec.get("category", ""), rec.get("quantity", 0),
                          rec.get("unit_price", 0.0), rec.get("supplier", ""), rec.get("reorder_level", 0),
                          now, sku))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO products (sku, name, category, quantity, unit_price, supplier, reorder_level, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sku, rec.get("name", ""), rec.get("category", ""), rec.get("quantity", 0),
                          rec.get("unit_price", 0.0), rec.get("supplier", ""), rec.get("reorder_level", 0), now))
                    added += 1
            conn.commit()

        return added, updated, skipped

    def log_sync(self, filename, added, updated, skipped):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO sync_log (filename, added, updated, skipped, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (filename, added, updated, skipped, datetime.now().isoformat(timespec="seconds")))
            conn.commit()

    def get_last_sync(self):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    # ---------- Column mapping persistence ----------

    def save_column_mapping(self, mapping: dict):
        with self._connect() as conn:
            for field, col in mapping.items():
                conn.execute("""
                    INSERT INTO column_mapping (field_name, excel_column)
                    VALUES (?, ?)
                    ON CONFLICT(field_name) DO UPDATE SET excel_column=excluded.excel_column
                """, (field, col))
            conn.commit()

    def get_column_mapping(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT field_name, excel_column FROM column_mapping").fetchall()
            return {r["field_name"]: r["excel_column"] for r in rows}
