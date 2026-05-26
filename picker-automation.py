import random
import pandas as pd
import re
import math
import json
import requests
from datetime import datetime

# ================================================================
# === $60 Boxes = $33 Cost (Cases 9@30 and 1@60)
# === $80 Boxes = $44 Cost
# === $100 Boxes = $55 Cost
# ================================================================
FILE = 'products_export_1 (9).csv'  # CSV file path
DESIRED_AVG_COST_PER_ITEM = 44     # target average cost per item
NUM_ITEMS = 100                      # requested count

INCLUDE_TAGS = ['']                 # e.g. ['inhouse', 'football']
EXCLUDE_TAGS = ['']                 # e.g. ['damaged']
INCLUDE_TYPES = ['']                 # e.g. ['inhouse', 'football']
EXCLUDE_TYPES = ['']

MINIMUM_COST = 0.0                 # per-item min (None = no limit)
MAXIMUM_COST = 0.0                 # per-item max (None = no limit)

COUNT_VARIANCE = 0.0                # ±20% allowed around NUM_ITEMS
AVG_TOLERANCE = 0.10                # ±10% around DESIRED_AVG_COST_PER_ITEM
COST_VARIANCE = 1.5                 # ±150%
ATTEMPTS = 1                       # attempts to find a valid list
SWAP_TRIES = 800                    # swaps per attempt to tune average
RANDOM_SEED = None                  # int for reproducibility, else None
N8N_WEBHOOK_URL = "http://localhost:5678/webhook-test/f5986e63-7897-4e92-a794-86009334f273"
# ================================================================


def send_to_webhook(payload, webhook_url=N8N_WEBHOOK_URL, timeout_seconds=60):
    try:
        resp = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        print(f"Webhook POST succeeded ({resp.status_code}).", flush=True)
        if resp.text:
            print(f"Webhook response: {resp.text}", flush=True)
        return True
    except requests.RequestException as exc:
        print(f"Webhook POST failed: {exc}", flush=True)
        return False

def decrement_inventory_in_csv(filename, items):
    # items = [{"sku": "...", "qty": 1}, ...]
    df = pd.read_csv(filename)
    df.columns = [str(col).title() for col in df.columns]

    required = ["Variant Sku", "Variant Inventory Qty"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    df["Variant Sku"] = df["Variant Sku"].astype(str)
    df["Variant Inventory Qty"] = pd.to_numeric(df["Variant Inventory Qty"], errors="coerce").fillna(0)

    for item in items:
        sku = str(item["sku"])
        qty = int(item.get("qty", 1))
        mask = df["Variant Sku"] == sku
        df.loc[mask, "Variant Inventory Qty"] = (df.loc[mask, "Variant Inventory Qty"] - qty).clip(lower=0)

    df.to_csv(filename, index=False)

def generate_random_list(filename=FILE,
                         desired_avg_cost_per_item=DESIRED_AVG_COST_PER_ITEM,
                         num_items=NUM_ITEMS,
                         minimum_cost=MINIMUM_COST,
                         maximum_cost=MAXIMUM_COST,
                         include_tags=None,
                         exclude_tags=None,
                         include_types=None,
                         exclude_types=None,
                         count_variance=0.0,
                         avg_tolerance=0.10,
                         attempts=200,
                         cost_variance=COST_VARIANCE,
                         swap_tries=800,
                         seed=RANDOM_SEED):

    if exclude_types is None:
        exclude_types = EXCLUDE_TYPES
    if include_types is None:
        include_types = INCLUDE_TYPES
    if exclude_tags is None:
        exclude_tags = EXCLUDE_TAGS
    if include_tags is None:
        include_tags = INCLUDE_TAGS
    if seed is not None:
        random.seed(seed)

    try:
        df = pd.read_csv(filename)
    except FileNotFoundError:
        print(f"\nError: The file '{filename}' was not found.", flush=True)
        return None

    # Standardize column names
    df.columns = [str(col).title() for col in df.columns]

    # Required columns
    required_columns = ['Tags', 'Cost Per Item', 'Variant Price',
                        'Variant Compare At Price', 'Variant Sku', 'Title']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        print(f"\nError: Your CSV file is missing the following required columns: {missing_cols}", flush=True)
        return None

    # Clean types
    df['Cost Per Item'] = pd.to_numeric(df['Cost Per Item'], errors='coerce')
    df['Variant Price'] = pd.to_numeric(df['Variant Price'], errors='coerce')
    df['Variant Compare At Price'] = pd.to_numeric(df['Variant Compare At Price'], errors='coerce')
    df.dropna(subset=['Cost Per Item', 'Variant Price'], inplace=True)
    df['Tags'] = df['Tags'].astype(str)
    df['Variant Sku'] = df['Variant Sku'].astype(str)

    # Tag filters
    if include_tags:
            tag_mask = pd.Series(False, index=df.index)
            for tag in include_tags:
                tag_mask |= df['Tags'].str.contains(tag, na=False, regex=True)
            df = df[tag_mask]

    if exclude_tags:
        for tag in exclude_tags:
            if tag:
                df = df[~df['Tags'].str.contains(tag, na=False, regex=True)]

    if include_types:
            type_mask = pd.Series(False, index=df.index)
            for type_val in include_types:
                type_mask |= df['Type'].str.contains(type_val, na=False, regex=True)
            df = df[type_mask]

    if exclude_types:
        for type_val in exclude_types:
            if type_val:
                df = df[~df['Type'].str.contains(type_val, na=False, regex=True)]

    # Optional per-item rails
    # if (minimum_cost is not None) or (maximum_cost is not None):
    cost_window = desired_avg_cost_per_item * cost_variance
    min_c = desired_avg_cost_per_item - cost_window if minimum_cost is None else float(minimum_cost)
    max_c = desired_avg_cost_per_item + cost_window if not maximum_cost else float(maximum_cost)
    df = df[df['Cost Per Item'].between(min_c, max_c)]

    if df.empty:
        print("\nNo items match your filters. Please adjust your criteria.", flush=True)
        return None

    # CRITICAL: keep a positional RangeIndex so .iloc and indices align everywhere
    df = df.reset_index(drop=True)

    def name_key(title):
        return ' '.join(str(title).split()[:2])

    number_tolerance = max(0, int(round(num_items * count_variance)))
    min_items = max(1, num_items - number_tolerance)
    max_items = min(len(df), num_items + number_tolerance)

    low_avg = desired_avg_cost_per_item * (1 - avg_tolerance)
    high_avg = desired_avg_cost_per_item * (1 + avg_tolerance)

    print(f"\n{df.shape[0]} total items matching all criteria", flush=True)
    print(f"Allowed costs pool based on Cost Variance: min/max ${min_c} / ${max_c}", flush=True)
    print(f"Actual costs pool: min/mean/max: ${df['Cost Per Item'].min():.2f} / "
          f"${df['Cost Per Item'].mean():.2f} / ${df['Cost Per Item'].max():.2f}", flush=True)
    print(f"Target count: {num_items} (allowed range: {min_items}–{max_items})", flush=True)
    print(f"Acceptable final average cost window based on tolerance: ${low_avg:.2f} – ${high_avg:.2f}", flush=True)

    def build_result(selected_indices):
        if not selected_indices:
            return None
        final_df = df.iloc[selected_indices]
        avg_cost = final_df['Cost Per Item'].mean()
        if (min_items <= len(final_df) <= max_items) and (low_avg <= avg_cost <= high_avg):
            items = []
            #todo: once get items needed in each spreadsheet add or change them here
            for _, row in final_df.iterrows():
                items.append({
                    "sku": row["Variant Sku"],
                    "qty": 1,
                    "cost": float(row["Cost Per Item"]) if pd.notna(row["Cost Per Item"]) else None,
                    "price": float(row["Variant Price"]) if pd.notna(row["Variant Price"]) else None,
                    "compare_price": float(row["Variant Compare At Price"]) if pd.notna(
                        row["Variant Compare At Price"]) else None,
                    "title": row["Title"] if "Title" in final_df.columns and pd.notna(row["Title"]) else None,
                    "variant_title": row["Variant Title"] if "Variant Title" in final_df.columns and pd.notna(
                        row["Variant Title"]) else None,
                })

            return {
                "job_id": "MYS" + datetime.now().strftime("%m%d%H%M"),
                "items": items,
                "summary": {
                    "skus": final_df["Variant Sku"].tolist(),
                    "avg_cost": float(avg_cost),
                    "total_cost": float(final_df["Cost Per Item"].sum()),
                    "item_count": int(len(final_df)),
                    "avg_price": float(final_df["Variant Price"].mean()),
                    "avg_compare_price": float(final_df["Variant Compare At Price"].mean())
                }
            }
        return None

    def improve_selection(sel_idx, k, target_avg, swap_tries):
        # Pools and selection are all POSITIONS into df (0..N-1)
        pool_idx = set(range(len(df))) - set(sel_idx)
        costs = df['Cost Per Item']  # Series with RangeIndex 0..N-1

        low_pool = [i for i in pool_idx if costs.iloc[i] <= target_avg]
        high_pool = [i for i in pool_idx if costs.iloc[i] > target_avg]

        sel_low_idx = [i for i in sel_idx if costs.iloc[i] <= target_avg]
        sel_high_idx = [i for i in sel_idx if costs.iloc[i] > target_avg]

        total = float(costs.iloc[sel_idx].sum())

        for _ in range(swap_tries):
            cur_avg = total / k
            need_up = (cur_avg < target_avg)

            if need_up and sel_low_idx and high_pool:
                out_i = random.choice(sel_low_idx)
                in_i = random.choice(high_pool)
            elif (not need_up) and sel_high_idx and low_pool:
                out_i = random.choice(sel_high_idx)
                in_i = random.choice(low_pool)
            else:
                if not pool_idx:
                    break
                out_i = random.choice(sel_idx)
                in_i = random.choice(list(pool_idx))

            # Uniqueness check (first two words + SKU)
            out_row = df.iloc[out_i]
            in_row = df.iloc[in_i]
            out_name = name_key(out_row['Title'])
            in_name = name_key(in_row['Title'])

            names = {name_key(df.iloc[j]['Title']) for j in sel_idx}
            skus = {df.iloc[j]['Variant Sku'] for j in sel_idx}
            names.discard(out_name)
            skus.discard(out_row['Variant Sku'])

            if (in_name in names) or (in_row['Variant Sku'] in skus):
                continue

            new_total = total - costs.iloc[out_i] + costs.iloc[in_i]
            new_avg = new_total / k
            if abs(new_avg - target_avg) < abs(cur_avg - target_avg):
                # commit swap
                total = new_total
                sel_idx[sel_idx.index(out_i)] = in_i  # replace one position

                pool_idx.remove(in_i)
                pool_idx.add(out_i)

                if in_i in low_pool:
                    low_pool.remove(in_i)
                if in_i in high_pool:
                    high_pool.remove(in_i)
                if costs.iloc[out_i] <= target_avg:
                    if out_i in sel_low_idx:
                        sel_low_idx.remove(out_i)
                    low_pool.append(out_i)
                else:
                    if out_i in sel_high_idx:
                        sel_high_idx.remove(out_i)
                    high_pool.append(out_i)

                if costs.iloc[in_i] <= target_avg:
                    sel_low_idx.append(in_i)
                else:
                    sel_high_idx.append(in_i)

                if low_avg <= new_avg <= high_avg:
                    break

        return sel_idx

    for _ in range(1, attempts + 1):
        k = random.randint(min_items, max_items)

        # Build a unique set of k positions from df (no separate shuffled df)
        order = list(range(len(df)))
        random.shuffle(order)
        sel_idx = []
        names_seen = set()
        skus_seen = set()

        for i in order:
            if len(sel_idx) >= k:
                break
            row = df.iloc[i]
            nkey = name_key(row['Title'])
            sku = row['Variant Sku']
            if (nkey not in names_seen) and (sku not in skus_seen):
                names_seen.add(nkey)
                skus_seen.add(sku)
                sel_idx.append(i)

        if len(sel_idx) < k:
            continue

        cur_avg = df['Cost Per Item'].iloc[sel_idx].mean()
        if not (low_avg <= cur_avg <= high_avg):
            sel_idx = improve_selection(sel_idx, k, desired_avg_cost_per_item, SWAP_TRIES)

        candidate = build_result(sel_idx)
        if candidate:
            return candidate

    print("\nNo valid list found matching criteria.", flush=True)
    print(f"Tried {ATTEMPTS} attempt(s) to find a minimum of {min_items} items and a maximum of {max_items} items\n"
          f"Acceptable final average cost ${low_avg:.2f}–${high_avg:.2f}. \nAverage item cost {df['Cost Per Item'].mean():.2f} ", flush=True)
    return None


# ==================================================================
# '''USE THE PROGRAM'''
# ==================================================================
if __name__ == "__main__":
    result = generate_random_list(
        FILE,
        DESIRED_AVG_COST_PER_ITEM,
        NUM_ITEMS,
        minimum_cost=MINIMUM_COST,
        maximum_cost=MAXIMUM_COST,
        count_variance=COUNT_VARIANCE,
        avg_tolerance=AVG_TOLERANCE,
        attempts=ATTEMPTS,
        swap_tries=SWAP_TRIES,
        seed=RANDOM_SEED
    )

    if result:
        print(result)
        send_to_webhook(result)
        # print(f"\n--- SUCCESS ---", flush=True)
        # print(f"Total Items: {result['item_count']}", flush=True)
        # print(f"Final Average Cost Per Item: ${result['avg_cost']:.2f}", flush=True)
        # print(f"Average Price (Variant Price): ${result['avg_price']:.2f}", flush=True)
        # print(f"Average Compare At Price: ${result['avg_compare_price']:.2f}", flush=True)
        # print(f"Total List Cost: ${result['total_cost']:.2f}", flush=True)
        # print("\nSelected SKUs:", flush=True)
        # print(result['skus'])
    else:
        print("\nProgram terminated: No valid list met the strict criteria.", flush=True)



#{'skus': ['RSA-01130', 'RSA-04781', 'RSA-11964', 'RSA-12396', 'RSA-10445', 'RSA-05791', 'RSA-08373', 'RSA-01651', 'RSA-08131', 'RSA-03354', 'RSA-09448', 'RSA-01936', 'RSA-01828', 'RSA-11977', 'RSA-12345', 'RSA-07925', 'RSA-02768', 'RSA-00007', 'RSA-12366', 'RSA-01749', 'RSA-11451', 'RSA-12342', 'RSA-07552', 'RSA-03823', 'RSA-03034', 'RSA-01408', 'RSA-02117', 'RSA-01831', 'RSA-12385', 'RSA-06277', 'RSA-09820', 'RSA-12369', 'RSA-01153', 'RSA-03361', 'RSA-06529', 'RSA-12021', 'RSA-01377', 'RSA-08290', 'RSA-02318', 'RSA-12368', 'RSA-03352', 'RSA-01349', 'RSA-03301', 'RSA-06540', 'RSA-09936', 'RSA-05343', 'RSA-08886', 'RSA-03075', 'RSA-07012', 'RSA-06251', 'RSA-05037', 'RSA-02765', 'RSA-12288', 'RSA-10869', 'RSA-00899', 'RSA-00063', 'RSA-10737', 'RSA-12371', 'RSA-01919', 'RSA-11765', 'RSA-12393', 'RSA-10782', 'RSA-12356', 'RSA-11978', 'RSA-12446', 'RSA-11783', 'RSA-08327', 'RSA-02523', 'RSA-01198', 'RSA-04153', 'RSA-12351', 'RSA-12394', 'RSA-10082', 'RSA-03878', 'RSA-09178', 'RSA-03328', 'RSA-04328', 'RSA-04146', 'RSA-03330', 'RSA-12344', 'RSA-12183', 'RSA-06935', 'RSA-02535', 'RSA-03846', 'RSA-11853', 'RSA-12363', 'RSA-10750', 'RSA-09975', 'RSA-11976', 'RSA-10748', 'RSA-12028', 'RSA-00618', 'RSA-10450', 'RSA-10743', 'RSA-11921', 'RSA-00982', 'RSA-10741', 'RSA-11818', 'RSA-06281', 'RSA-01402', 'RSA-12310', 'RSA-12341', 'RSA-12375', 'RSA-10631', 'RSA-11984', 'RSA-00979', 'RSA-12530', 'RSA-02793', 'RSA-11400', 'RSA-00161', 'RSA-10365', 'RSA-10485', 'RSA-09211', 'RSA-04212', 'RSA-12343', 'RSA-11415', 'RSA-04300', 'RSA-00907', 'RSA-10742', 'RSA-12392', 'RSA-12372', 'RSA-02726', 'RSA-03053', 'RSA-12359', 'RSA-07456', 'RSA-10676', 'RSA-01360', 'RSA-01379', 'RSA-12395', 'RSA-10311', 'RSA-11475', 'RSA-12350', 'RSA-03899', 'RSA-11100'],
# 'avg_cost': 29.417910447761194,
# 'total_cost': 3942.0,
# 'item_count': 134,
# 'avg_price': 47.41044776119403,
# 'avg_compare_price': 66.54977611940299}
