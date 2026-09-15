from collections import OrderedDict
from dataclasses import dataclass

import pandas as pd

from picker.bags import GOLD_BAG, GREEN_BAG, bag_group_from_tags
from picker.selection import name_key, team_duplicate_limit_count, team_key_mapper


EDITOR_COLUMNS = [
    "sku",
    "qty",
    "inventory",
    "cost",
    "price",
    # "compare_price",
    "title",
    "tags",
    "bag_group",
]
CATALOG_FIELDS = [
    "Variant Sku",
    "Cost Per Item",
    "Variant Price",
    "Variant Compare At Price",
    "Title",
    "Variant Title",
    "Tags",
    "Variant Inventory Qty",
]


@dataclass
class Catalog:
    rows: dict[str, dict]
    ambiguous_skus: set[str]


@dataclass
class ReviewResolution:
    display_df: pd.DataFrame
    selected_df: pd.DataFrame
    errors: list[str]


def normalize_sku(value):
    if value is None or pd.isna(value):
        return ""
    normalized = str(value).strip().casefold()
    return "" if normalized in {"", "nan"} else normalized


def _comparable(value):
    return None if value is None or pd.isna(value) else str(value)


def build_catalog(df):
    rows = {}
    fingerprints = {}
    ambiguous_skus = set()
    for _, source_row in df.iterrows():
        key = normalize_sku(source_row.get("Variant Sku"))
        if not key:
            continue
        record = {field: source_row.get(field) for field in CATALOG_FIELDS}
        fingerprint = tuple(_comparable(record[field]) for field in CATALOG_FIELDS)
        if key in fingerprints and fingerprints[key] != fingerprint:
            ambiguous_skus.add(key)
            continue
        rows[key] = record
        fingerprints[key] = fingerprint

    return Catalog(rows=rows, ambiguous_skus=ambiguous_skus)


def editor_rows_from_items(items):
    rows = []
    for item in items:
        rows.append(
            {
                "sku": item.get("sku", ""),
                "qty": item.get("qty", 1),
                "cost": item.get("cost"),
                "price": item.get("price"),
                "compare_price": item.get("compare_price"),
                "title": item.get("title"),
                "tags": item.get("tags", ""),
                "inventory": item.get("inventory"),
                "bag_group": item.get("bag_group", bag_group_from_tags(item.get("tags", ""))),
            }
        )
    return pd.DataFrame(rows, columns=EDITOR_COLUMNS)


def _parse_quantity(value):
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number.is_integer() or number < 1:
        return None
    return int(number)


def _available_quantity(value):
    if value is None or pd.isna(value):
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _display_row(record, quantity):
    tags = record.get("Tags")
    return {
        "sku": record.get("Variant Sku"),
        "qty": quantity,
        "cost": record.get("Cost Per Item"),
        "price": record.get("Variant Price"),
        "compare_price": record.get("Variant Compare At Price"),
        "title": record.get("Title"),
        "tags": tags,
        "inventory": record.get("Variant Inventory Qty"),
        "bag_group": bag_group_from_tags(tags),
    }


def resolve_editor_rows(editor_df, catalog):
    merged = OrderedDict()
    invalid_rows = []
    errors = []

    for position, row in editor_df.reset_index(drop=True).iterrows():
        raw_sku = row.get("sku")
        key = normalize_sku(raw_sku)
        quantity = _parse_quantity(row.get("qty"))
        row_number = position + 1

        if not key:
            errors.append(f"Row {row_number}: enter a SKU or delete the row.")
        elif key in catalog.ambiguous_skus:
            errors.append(f"Row {row_number}: SKU '{str(raw_sku).strip()}' has conflicting rows in the CSV.")
        elif key not in catalog.rows:
            errors.append(f"Row {row_number}: SKU '{str(raw_sku).strip()}' was not found in the uploaded CSV.")
        if quantity is None:
            errors.append(f"Row {row_number}: quantity must be a positive whole number.")

        if not key or key in catalog.ambiguous_skus or key not in catalog.rows or quantity is None:
            invalid_rows.append(
                {
                    "sku": "" if raw_sku is None or pd.isna(raw_sku) else str(raw_sku).strip(),
                    "qty": row.get("qty"),
                    "cost": None,
                    "price": None,
                    "compare_price": None,
                    "title": None,
                    "tags": None,
                    "inventory": None,
                    "bag_group": None,
                }
            )
            continue

        if key not in merged:
            merged[key] = {"record": catalog.rows[key], "qty": 0}
        merged[key]["qty"] += quantity

    for value in merged.values():
        record = value["record"]
        sku = record.get("Variant Sku")
        quantity = value["qty"]
        available = _available_quantity(record.get("Variant Inventory Qty"))
        if available == 0:
            errors.append(f"SKU {sku} has no available inventory in the uploaded CSV.")
        elif quantity > available:
            errors.append(
                f"SKU {sku} requests quantity {quantity}, but only {available} is available in the uploaded CSV."
            )

    display_rows = [_display_row(value["record"], value["qty"]) for value in merged.values()]
    display_rows.extend(invalid_rows)
    display_df = pd.DataFrame(display_rows, columns=EDITOR_COLUMNS)

    selected_rows = []
    for value in merged.values():
        for _ in range(value["qty"]):
            selected_rows.append(value["record"])
    selected_df = pd.DataFrame(selected_rows, columns=CATALOG_FIELDS)

    return ReviewResolution(display_df=display_df, selected_df=selected_df, errors=errors)


def editable_signature(editor_df):
    signature = []
    for _, row in editor_df.reset_index(drop=True).iterrows():
        sku = "" if row.get("sku") is None or pd.isna(row.get("sku")) else str(row.get("sku")).strip()
        qty = row.get("qty")
        qty_value = None if qty is None or pd.isna(qty) else str(qty)
        signature.append((sku, qty_value))
    return tuple(signature)


def review_warnings(selected_df, config, allowed_skus=None):
    warnings = []
    if selected_df.empty:
        warnings.append("The edited list is empty.")
    item_count = len(selected_df)
    number_tolerance = max(0, int(round(config.num_items * config.count_variance)))
    min_items = max(1, config.num_items - number_tolerance)
    max_items = config.num_items + number_tolerance
    if not min_items <= item_count <= max_items:
        warnings.append(f"Item count is {item_count}; the configured range is {min_items}-{max_items}.")

    low_average = config.desired_avg_cost_per_item * (1 - config.avg_tolerance)
    high_average = config.desired_avg_cost_per_item * (1 + config.avg_tolerance)
    average_cost = None if selected_df.empty else float(selected_df["Cost Per Item"].mean())
    if average_cost is not None and not low_average <= average_cost <= high_average:
        warnings.append(
            f"Average cost is \${average_cost:.2f} the configured range is \${low_average:.2f}-\${high_average:.2f}."
        )

    quantities = selected_df["Variant Sku"].value_counts(sort=False).astype(int)
    if not config.allow_duplicates:
        duplicate_skus = quantities[quantities > 1]
        if not duplicate_skus.empty:
            warnings.append("Duplicate SKUs are present while duplicate SKUs are disabled.")
        unique_products = selected_df.drop_duplicates("Variant Sku")
        names = unique_products["Title"].map(name_key)
        if names.duplicated(keep=False).any():
            warnings.append("Multiple SKUs for the same first-two-word player name are present.")

    if allowed_skus is not None:
        outside_filters = sorted(
            {
                str(sku)
                for sku in selected_df["Variant Sku"]
                if normalize_sku(sku) not in allowed_skus
            }
        )
        if outside_filters:
            warnings.append("SKUs outside the generated run's filters: " + ", ".join(outside_filters))

    bag_counts = selected_df["Tags"].map(bag_group_from_tags).value_counts().to_dict()
    actual_gold = int(bag_counts.get(GOLD_BAG, 0))
    if config.gold_bag_minimum > 0 and actual_gold != config.gold_bag_minimum:
        warnings.append(
            f"{GOLD_BAG} count is {actual_gold}; requested exact count is {config.gold_bag_minimum}."
        )

    actual_green = int(bag_counts.get(GREEN_BAG, 0))
    if actual_green < config.green_bag_minimum:
        warnings.append(
            f"{GREEN_BAG} count is {actual_green}; requested minimum is {config.green_bag_minimum}."
        )

    if config.limit_team_duplicates:
        team_keys = selected_df["Tags"].map(team_key_mapper(config)).dropna()
        team_counts = team_keys.value_counts()
        limit = team_duplicate_limit_count(config, item_count)
        over_limit = [f"{team} ({int(count)})" for team, count in team_counts.items() if count > limit]
        if over_limit:
            warnings.append(f"Team limit is {limit}; over-limit teams: " + ", ".join(over_limit))

    return warnings
