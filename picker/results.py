from dataclasses import asdict, is_dataclass

import pandas as pd

from picker.selection import team_key_from_tags


class FailurePayload(dict):
    def __bool__(self):
        return False


def build_items(selected_df):
    items = []
    for _, rows in selected_df.groupby("Variant Sku", sort=False):
        row = rows.iloc[0]
        items.append({
            "sku": row["Variant Sku"],
            "qty": int(len(rows)),
            "cost": float(row["Cost Per Item"]) if pd.notna(row["Cost Per Item"]) else None,
            "price": float(row["Variant Price"]) if pd.notna(row["Variant Price"]) else None,
            "compare_price": (
                float(row["Variant Compare At Price"])
                if pd.notna(row["Variant Compare At Price"])
                else None
            ),
            "title": row["Title"] if "Title" in selected_df.columns and pd.notna(row["Title"]) else None,
            "variant_title": (
                row["Variant Title"]
                if "Variant Title" in selected_df.columns and pd.notna(row["Variant Title"])
                else None
            ),
        })
    return items


def build_summary(selected_df, leagues=None):
    avg_cost = selected_df["Cost Per Item"].mean()
    sku_quantities = selected_df["Variant Sku"].value_counts(sort=False).astype(int).to_dict()
    team_counts = (
        selected_df["Tags"]
        .map(lambda tags: team_key_from_tags(tags, leagues))
        .dropna()
        .value_counts(sort=True)
        .astype(int)
        .to_dict()
    )
    return {
        "skus": selected_df["Variant Sku"].tolist(),
        "sku_quantities": sku_quantities,
        "team_counts": team_counts,
        "avg_cost": float(avg_cost),
        "total_cost": float(selected_df["Cost Per Item"].sum()),
        "item_count": int(len(selected_df)),
        "avg_price": float(selected_df["Variant Price"].mean()),
        "avg_compare_price": float(selected_df["Variant Compare At Price"].mean()),
    }


def build_result_payload(selected_df, *, job_id, emails, leagues=None):
    return {
        "job_id": job_id,
        "emails": normalize_emails(emails),
        "items": build_items(selected_df),
        "summary": build_summary(selected_df, leagues=leagues),
    }


def build_result_from_selection(selection_result, *, job_id, emails, leagues=None):
    if selection_result is None:
        return None
    return build_result_payload(selection_result.selected_df, job_id=job_id, emails=emails, leagues=leagues)


def build_failure_payload(*, job_id, code, message, details=None, selection_stats=None):
    return FailurePayload(
        {
            "ok": False,
            "job_id": job_id,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
            "selection_stats": serialize_selection_stats(selection_stats),
        }
    )


def serialize_selection_stats(selection_stats):
    if selection_stats is None:
        return None
    if is_dataclass(selection_stats):
        return asdict(selection_stats)
    return selection_stats


def is_failure_payload(payload):
    return isinstance(payload, dict) and payload.get("ok") is False and "error" in payload


def normalize_emails(emails):
    if emails is None:
        return {"pick": "", "listing": "", "invoice": ""}

    return {
        "pick": emails.get("pick") or "",
        "listing": emails.get("listing") or "",
        "invoice": emails.get("invoice") or "",
    }
