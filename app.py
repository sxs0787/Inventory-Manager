"""
app.py
------
Desktop UI for the Inventory Manager.

Run with:  python app.py

Features:
  - View/search all products in a sortable table
  - Add, edit, delete products manually
  - Sync (import) data from an Excel/CSV file, matching existing
    items by SKU so re-importing an updated file updates rather
    than duplicates rows
  - Remembers the column mapping from your last sync so re-syncing
    the same style of file is one click
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os

from database import InventoryDB
from excel_sync import read_excel_columns, auto_detect_mapping, load_records, ALL_FIELDS

FIELD_LABELS = {
    "sku": "SKU",
    "name": "Product Name",
    "category": "Category",
    "quantity": "Quantity",
    "unit_price": "Unit Price",
    "supplier": "Supplier",
    "reorder_level": "Reorder Level",
}


class InventoryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Inventory Manager")
        self.geometry("1000x600")
        self.minsize(800, 500)

        self.db = InventoryDB()

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

        self.refresh_table()

    # ---------------- UI construction ----------------

    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Sync from Excel...", command=self.sync_from_excel).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bar, text="Add Product", command=self.add_product_dialog).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Edit Selected", command=self.edit_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Delete Selected", command=self.delete_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Refresh", command=self.refresh_table).pack(side=tk.LEFT, padx=6)

        ttk.Label(bar, text="Search:").pack(side=tk.LEFT, padx=(24, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_table())
        search_entry = ttk.Entry(bar, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT)

    def _build_table(self):
        container = ttk.Frame(self, padding=(8, 0, 8, 8))
        container.pack(fill=tk.BOTH, expand=True)

        columns = ["sku", "name", "category", "quantity", "unit_price", "supplier", "reorder_level"]
        self.tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")

        widths = {"sku": 90, "name": 200, "category": 120, "quantity": 80,
                  "unit_price": 90, "supplier": 130, "reorder_level": 100}

        for col in columns:
            self.tree.heading(col, text=FIELD_LABELS[col], command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=widths.get(col, 100), anchor=tk.W)

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        # low stock highlighting
        self.tree.tag_configure("low_stock", background="#ffe0e0")

        self._sort_state = {"col": None, "reverse": False}

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Ready.")
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self.status_var).pack(side=tk.LEFT)

    # ---------------- table data ----------------

    def refresh_table(self):
        search = self.search_var.get().strip()
        products = self.db.get_all_products(search if search else None)

        for row in self.tree.get_children():
            self.tree.delete(row)

        for p in products:
            low_stock = p["quantity"] <= p["reorder_level"]
            tags = ("low_stock",) if low_stock else ()
            self.tree.insert("", tk.END, iid=str(p["id"]), tags=tags, values=(
                p["sku"], p["name"], p["category"], p["quantity"],
                f'{p["unit_price"]:.2f}', p["supplier"], p["reorder_level"]
            ))

        self.status_var.set(f"{len(products)} product(s) shown.")

    def _sort_by(self, col):
        reverse = self._sort_state["col"] == col and not self._sort_state["reverse"]
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]

        def try_num(v):
            try:
                return float(v)
            except ValueError:
                return v.lower()

        items.sort(key=lambda t: try_num(t[0]), reverse=reverse)
        for index, (_, k) in enumerate(items):
            self.tree.move(k, "", index)

        self._sort_state = {"col": col, "reverse": reverse}

    def _selected_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    # ---------------- manual CRUD ----------------

    def add_product_dialog(self):
        ProductDialog(self, self.db, on_save=self.refresh_table)

    def edit_selected(self):
        pid = self._selected_id()
        if pid is None:
            messagebox.showinfo("No selection", "Select a product to edit first.")
            return
        product = self.db.get_product(pid)
        ProductDialog(self, self.db, product=product, on_save=self.refresh_table)

    def delete_selected(self):
        pid = self._selected_id()
        if pid is None:
            messagebox.showinfo("No selection", "Select a product to delete first.")
            return
        product = self.db.get_product(pid)
        if messagebox.askyesno("Confirm delete", f"Delete '{product['name']}' ({product['sku']})?"):
            self.db.delete_product(pid)
            self.refresh_table()

    # ---------------- Excel sync ----------------

    def sync_from_excel(self):
        filepath = filedialog.askopenfilename(
            title="Select Excel or CSV file",
            filetypes=[("Excel/CSV files", "*.xlsx *.xls *.csv"), ("All files", "*.*")]
        )
        if not filepath:
            return

        try:
            columns = read_excel_columns(filepath)
        except Exception as e:
            messagebox.showerror("Could not read file", str(e))
            return

        auto_mapping = auto_detect_mapping(columns)
        MappingDialog(self, columns, auto_mapping, self.db,
                      on_confirm=lambda mapping: self._run_sync(filepath, mapping))

    def _run_sync(self, filepath, mapping):
        try:
            records = load_records(filepath, mapping)
            added, updated, skipped = self.db.upsert_from_excel(records)
            self.db.log_sync(os.path.basename(filepath), added, updated, skipped)
            self.db.save_column_mapping(mapping)
        except Exception as e:
            messagebox.showerror("Sync failed", str(e))
            return

        self.refresh_table()
        messagebox.showinfo(
            "Sync complete",
            f"Added: {added}\nUpdated: {updated}\nSkipped (missing SKU): {skipped}"
        )
        self.status_var.set(f"Synced '{os.path.basename(filepath)}' — {added} added, {updated} updated, {skipped} skipped.")


class ProductDialog(tk.Toplevel):
    """Add / Edit product form."""

    def __init__(self, parent, db: InventoryDB, product=None, on_save=None):
        super().__init__(parent)
        self.db = db
        self.product = product
        self.on_save = on_save
        self.title("Edit Product" if product else "Add Product")
        self.resizable(False, False)
        self.grab_set()

        self.vars = {}
        fields = ["sku", "name", "category", "quantity", "unit_price", "supplier", "reorder_level"]

        form = ttk.Frame(self, padding=16)
        form.pack(fill=tk.BOTH, expand=True)

        for i, field in enumerate(fields):
            ttk.Label(form, text=FIELD_LABELS[field] + ":").grid(row=i, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar()
            if product:
                var.set(str(product.get(field, "")))
            entry = ttk.Entry(form, textvariable=var, width=32)
            entry.grid(row=i, column=1, pady=4, padx=(8, 0))
            self.vars[field] = var

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=len(fields), column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=4)

    def _save(self):
        sku = self.vars["sku"].get().strip()
        name = self.vars["name"].get().strip()
        if not sku or not name:
            messagebox.showerror("Missing data", "SKU and Product Name are required.", parent=self)
            return

        try:
            quantity = int(float(self.vars["quantity"].get() or 0))
            unit_price = float(self.vars["unit_price"].get() or 0)
            reorder_level = int(float(self.vars["reorder_level"].get() or 0))
        except ValueError:
            messagebox.showerror("Invalid number", "Quantity, Unit Price, and Reorder Level must be numbers.", parent=self)
            return

        category = self.vars["category"].get().strip()
        supplier = self.vars["supplier"].get().strip()

        if self.product:
            existing = self.db.sku_exists(sku)
            if existing and existing != self.product["id"]:
                messagebox.showerror("Duplicate SKU", f"Another product already uses SKU '{sku}'.", parent=self)
                return
            self.db.update_product(self.product["id"], sku, name, category, quantity, unit_price, supplier, reorder_level)
        else:
            if self.db.sku_exists(sku):
                messagebox.showerror("Duplicate SKU", f"A product with SKU '{sku}' already exists.", parent=self)
                return
            self.db.add_product(sku, name, category, quantity, unit_price, supplier, reorder_level)

        if self.on_save:
            self.on_save()
        self.destroy()


class MappingDialog(tk.Toplevel):
    """Lets the user confirm/adjust which Excel column maps to which field before syncing."""

    def __init__(self, parent, excel_columns, auto_mapping, db: InventoryDB, on_confirm=None):
        super().__init__(parent)
        self.title("Match Excel Columns")
        self.resizable(False, False)
        self.grab_set()
        self.on_confirm = on_confirm

        saved_mapping = db.get_column_mapping()

        ttk.Label(self, text="Match each field to a column from your Excel file:",
                  padding=(16, 16, 16, 8)).pack(anchor=tk.W)

        form = ttk.Frame(self, padding=(16, 0, 16, 8))
        form.pack(fill=tk.BOTH, expand=True)

        options = ["(none)"] + excel_columns
        self.combo_vars = {}

        for i, field in enumerate(ALL_FIELDS):
            required = field in ("sku", "name")
            label_text = FIELD_LABELS[field] + (" *" if required else "")
            ttk.Label(form, text=label_text).grid(row=i, column=0, sticky=tk.W, pady=3)

            var = tk.StringVar()
            # Prefer a previously-saved mapping if the column still exists in this file,
            # otherwise fall back to the auto-detected guess.
            preferred = saved_mapping.get(field)
            guess = auto_mapping.get(field)
            if preferred and preferred in excel_columns:
                var.set(preferred)
            elif guess:
                var.set(guess)
            else:
                var.set("(none)")

            combo = ttk.Combobox(form, textvariable=var, values=options, width=28, state="readonly")
            combo.grid(row=i, column=1, padx=(8, 0), pady=3)
            self.combo_vars[field] = var

        ttk.Label(self, text="* Required — rows without these will be skipped.",
                  padding=(16, 0)).pack(anchor=tk.W)

        btn_frame = ttk.Frame(self, padding=16)
        btn_frame.pack()
        ttk.Button(btn_frame, text="Sync", command=self._confirm).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=4)

    def _confirm(self):
        mapping = {}
        for field, var in self.combo_vars.items():
            value = var.get()
            mapping[field] = None if value == "(none)" else value

        if not mapping.get("sku") or not mapping.get("name"):
            messagebox.showerror("Missing required fields",
                                  "You must map both SKU and Product Name to a column.", parent=self)
            return

        self.destroy()
        if self.on_confirm:
            self.on_confirm(mapping)


if __name__ == "__main__":
    app = InventoryApp()
    app.mainloop()
