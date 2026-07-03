"""
excel_sync.py
-------------
Reads product data out of an Excel file (.xlsx/.xls/.csv) and converts
it into a list of plain dicts the database module can upsert.

Handles the fact that different Excel files will use different column
names by working off a "mapping" dict: {our_field: excel_column_name}.
"""

import pandas as pd

REQUIRED_FIELDS = ["sku", "name"]
ALL_FIELDS = ["sku", "name", "category", "quantity", "unit_price", "supplier", "reorder_level"]

# Common header aliases we try to auto-detect, per field.
AUTO_ALIASES = {
    "sku": ["sku", "product id", "product code", "item code", "item number", "id", "code"],
    "name": ["name", "product name", "description", "item", "item name", "title"],
    "category": ["category", "type", "product category", "department"],
    "quantity": ["quantity", "qty", "stock", "on hand", "quantity on hand", "count"],
    "unit_price": ["unit price", "price", "cost", "unit cost", "price per unit"],
    "supplier": ["supplier", "vendor", "manufacturer", "supplier name"],
    "reorder_level": ["reorder level", "reorder point", "min stock", "minimum stock", "safety stock"],
}


def read_excel_columns(filepath):
    """Return the list of column headers found in the file (first sheet)."""
    df = _read_any(filepath, nrows=0)
    return list(df.columns)


def auto_detect_mapping(columns):
    """
    Given a list of Excel column headers, guess which one corresponds
    to each of our fields. Returns {field: excel_column_or_None}.
    """
    lower_map = {c.strip().lower(): c for c in columns}
    mapping = {}
    for field, aliases in AUTO_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in lower_map:
                found = lower_map[alias]
                break
        mapping[field] = found
    return mapping


def load_records(filepath, mapping):
    """
    Read the Excel file and return a list of dicts using our field
    names, based on the supplied mapping {field: excel_column}.
    Rows missing a value for a required field are still returned;
    the caller (database layer) decides whether to skip them.
    """
    df = _read_any(filepath)
    records = []

    for _, row in df.iterrows():
        rec = {}
        for field in ALL_FIELDS:
            col = mapping.get(field)
            if col and col in df.columns:
                value = row[col]
                rec[field] = _clean_value(field, value)
            else:
                rec[field] = "" if field not in ("quantity", "unit_price", "reorder_level") else 0
        records.append(rec)

    return records


def _clean_value(field, value):
    if pd.isna(value):
        return "" if field not in ("quantity", "unit_price", "reorder_level") else 0

    if field == "quantity" or field == "reorder_level":
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return 0
    if field == "unit_price":
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    if field == "sku":
        return str(value).strip()
    return str(value).strip()


def _read_any(filepath, nrows=None):
    filepath = str(filepath)
    if filepath.lower().endswith(".csv"):
        return pd.read_csv(filepath, nrows=nrows)
    return pd.read_excel(filepath, nrows=nrows)
