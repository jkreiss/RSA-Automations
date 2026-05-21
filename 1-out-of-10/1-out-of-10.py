import random
import pandas as pd
import re
import math
import json
from urllib import request, error

# ================================================================
# === $60 Boxes = $33 Cost (Cases 9@30 and 1@60)
# === $80 Boxes = $44 Cost
# === $100 Boxes = $55 Cost
# ================================================================
FILE = '../products_export_1 (16).csv'  # CSV file path
DESIRED_AVG_COST_PER_ITEM = 44     # target average cost per item
NUM_ITEMS_PER_RUN = 10                      # requested count
RUNS = 1

INCLUDE_TAGS = ['']                 # e.g. ['inhouse', 'football']
EXCLUDE_TAGS = ['']                 # e.g. ['damaged']
INCLUDE_TYPES = ['Autographed Football Jerseys']                 # e.g. ['inhouse', 'football']
EXCLUDE_TYPES = ['']

MINIMUM_COST = 0.0                 # per-item min (None = no limit)
MAXIMUM_COST = 0.0                 # per-item max (None = no limit)

COUNT_VARIANCE = 0.0                # ±20% allowed around NUM_ITEMS
AVG_TOLERANCE = 0.10                # ±10% around DESIRED_AVG_COST_PER_ITEM
COST_VARIANCE = 2.5                 # ±150%
ATTEMPTS = 200                      # attempts to find a valid list
SWAP_TRIES = 800                    # swaps per attempt to tune average
RANDOM_SEED = None                  # int for reproducibility, else None
N8N_WEBHOOK_URL = "http://192.168.1.25:5678/webhook-test/f5986e63-7897-4e92-a794-86009334f273"
# ================================================================


def name_key(title):
    return ' '.join(str(title).split()[:2])


def selection_is_valid(df, selected_indices, min_items, max_items, low_avg, high_avg):
    if not selected_indices:
        return False

    final_df = df.iloc[selected_indices]
    avg_cost = final_df['Cost Per Item'].mean()
    return (min_items <= len(final_df) <= max_items) and (low_avg <= avg_cost <= high_avg)


def build_result(df, run_selections):
    runs_payload = []
    merged_items = []

    for run_data in run_selections:
        run_number = run_data["run_number"]
        selected_indices = run_data["selected_indices"]
        run_df = df.iloc[selected_indices]
        run_items = []

        for _, row in run_df.iterrows():
            item = {
                "sku": row["Variant Sku"],
                "qty": 1,
                "cost": float(row["Cost Per Item"]) if pd.notna(row["Cost Per Item"]) else None,
                "price": float(row["Variant Price"]) if pd.notna(row["Variant Price"]) else None,
                "compare_price": float(row["Variant Compare At Price"]) if pd.notna(
                    row["Variant Compare At Price"]) else None,
                "title": row["Title"] if "Title" in run_df.columns and pd.notna(row["Title"]) else None,
                "variant_title": row["Variant Title"] if "Variant Title" in run_df.columns and pd.notna(
                    row["Variant Title"]) else None,
                "run_number": run_number,
            }
            run_items.append(item)
            merged_items.append(item)

        runs_payload.append({
            "run_number": run_number,
            "items": run_items,
            "summary": {
                "skus": run_df["Variant Sku"].tolist(),
                "avg_cost": float(run_df["Cost Per Item"].mean()),
                "total_cost": float(run_df["Cost Per Item"].sum()),
                "item_count": int(len(run_df)),
                "avg_price": float(run_df["Variant Price"].mean()),
                "avg_compare_price": float(run_df["Variant Compare At Price"].mean())
            }
        })

    total_cost = sum(item["cost"] for item in merged_items if item.get("cost") is not None)
    total_price = [item["price"] for item in merged_items if item.get("price") is not None]
    total_compare = [item["compare_price"] for item in merged_items if item.get("compare_price") is not None]

    return {
        "job_id": "JOB-001",
        "runs": runs_payload,
        # "items": merged_items,
        "summary": {
            "run_count": len(runs_payload),
            "item_count": len(merged_items),
            "avg_cost": (total_cost / len(merged_items)) if merged_items else 0.0,
            "total_cost": float(total_cost),
            "avg_price": (sum(total_price) / len(total_price)) if total_price else None,
            "avg_compare_price": (sum(total_compare) / len(total_compare)) if total_compare else None,
            "skus": [item["sku"] for item in merged_items],
        }
    }


def improve_selection(
    df,
    sel_idx,
    k,
    target_avg,
    low_avg,
    high_avg,
    swap_tries,
    forbidden_names=None,
    forbidden_skus=None,
    locked_indices=None,
):
    forbidden_names = forbidden_names or set()
    forbidden_skus = forbidden_skus or set()
    locked_indices = set(locked_indices or [])

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

        if out_i in locked_indices:
            continue

        # Uniqueness check (first two words + SKU)
        out_row = df.iloc[out_i]
        in_row = df.iloc[in_i]
        out_name = name_key(out_row['Title'])
        in_name = name_key(in_row['Title'])

        if (in_name in forbidden_names) or (in_row['Variant Sku'] in forbidden_skus):
            continue

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


def generate_random_list(filename=FILE,
                         desired_avg_cost_per_item=DESIRED_AVG_COST_PER_ITEM,
                         num_items=NUM_ITEMS_PER_RUN,
                         runs=RUNS,
                         include_tags=INCLUDE_TAGS,
                         exclude_tags=EXCLUDE_TAGS,
                         include_types=INCLUDE_TYPES,
                         exclude_types=EXCLUDE_TYPES,
                         minimum_cost=MINIMUM_COST,
                         maximum_cost=MAXIMUM_COST,
                         count_variance=0.20,
                         avg_tolerance=0.10,
                         attempts=200,
                         cost_variance=COST_VARIANCE,
                         swap_tries=800,
                         seed=RANDOM_SEED):

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
        for tag in include_tags:
            if tag:
                # pattern = f'(?i)\\b{re.escape(tag)}\\b'
                df = df[df['Tags'].str.contains(tag, na=False, regex=True)]
    if exclude_tags:
        for tag in exclude_tags:
            if tag:
                df = df[~df['Tags'].str.contains(tag, na=False, regex=True)]

    if include_types:
        for type_val in include_types:
            if type_val:
                print(type_val)
                # pattern = f'(?i)\\b{re.escape(type_val)}\\b'
                df = df[~df['Type'].str.contains(type_val, na=False, regex=True)]

    if exclude_types:
        for type_val in exclude_types:
            if type_val:
                # pattern = f'(?i)\\b{re.escape(type_val)}\\b'
                df = df[~df['Type'].str.contains(type_val, na=False, regex=True)]

    # Optional per-item rails
    # if (minimum_cost is not None) or (maximum_cost is not None):
    # TODO: ASK IF HE WANTS $0.0 THINGS INCLUDED OR EXCLUDED
    cost_high = desired_avg_cost_per_item * cost_variance
    high_df = df[df['Cost Per Item'].between(cost_high - cost_high*avg_tolerance, cost_high + cost_high*avg_tolerance)]
    min_c = 0 if minimum_cost is None else float(minimum_cost)
    max_c = cost_high if not maximum_cost else float(maximum_cost)
    df = df[df['Cost Per Item'].between(min_c, max_c)]

    if df.empty:
        print("\nNo items match your filters. Please adjust your criteria.", flush=True)
        return None

    # CRITICAL: keep a positional RangeIndex so .iloc and indices align everywhere
    df = df.reset_index(drop=True)
    high_idx_pool = df[
        df['Cost Per Item'].between(cost_high - cost_high * avg_tolerance, cost_high + cost_high * avg_tolerance)
    ].index.tolist()
    if not high_idx_pool:
        print("\nNo high-band items found to append to each run.", flush=True)
        return None

    number_tolerance = max(0, int(round(num_items * count_variance)))
    min_items = max(1, num_items - number_tolerance)
    max_items = min(len(df), num_items + number_tolerance)
    min_items_base = max(0, min_items - 1)
    max_items_base = max(0, max_items - 1)

    low_avg = desired_avg_cost_per_item * (1 - avg_tolerance)
    high_avg = desired_avg_cost_per_item * (1 + avg_tolerance)

    print(f"\n{df.shape[0]} total items matching all criteria.", flush=True)
    print(df.head(), df.shape, df['Cost Per Item'].head())
    print(f"Pool cost min/mean/max: ${df['Cost Per Item'].min():.2f} / "
          f"${df['Cost Per Item'].mean():.2f} / ${df['Cost Per Item'].max():.2f}", flush=True)
    print(f"Target count: {num_items} (allowed range: {min_items}–{max_items})", flush=True)
    print(f"Window based on avg tolerance: ${low_avg:.2f} – ${high_avg:.2f}", flush=True)
    print("___________________", flush=True)

    run_selections = []
    global_names_seen = set()
    global_skus_seen = set()

    for run_number in range(1, runs + 1):
        run_sel_idx = None

        for _ in range(1, attempts + 1):

            k = random.randint(min_items_base, max_items_base)

            # Build a unique set of k positions from df (no separate shuffled df)
            order = list(range(len(df)))
            random.shuffle(order)
            sel_idx = []
            names_seen = set(global_names_seen)
            skus_seen = set(global_skus_seen)

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
                sel_idx = improve_selection(
                    df=df,
                    sel_idx=sel_idx,
                    k=k,
                    target_avg=desired_avg_cost_per_item,
                    low_avg=low_avg,
                    high_avg=high_avg,
                    swap_tries=swap_tries,
                    forbidden_names=global_names_seen,
                    forbidden_skus=global_skus_seen,
                )

            if selection_is_valid(
                df=df,
                selected_indices=sel_idx,
                min_items=min_items_base,
                max_items=max_items_base,
                low_avg=low_avg,
                high_avg=high_avg,
            ):
                names_seen_now = {name_key(df.iloc[i]['Title']) for i in sel_idx}
                skus_seen_now = {df.iloc[i]['Variant Sku'] for i in sel_idx}
                available_high = []
                for hi in high_idx_pool:
                    row = df.iloc[hi]
                    nk = name_key(row['Title'])
                    sku = row['Variant Sku']
                    if nk in global_names_seen or sku in global_skus_seen:
                        continue
                    if nk in names_seen_now or sku in skus_seen_now:
                        continue
                    available_high.append(hi)

                if not available_high:
                    continue

                high_idx = random.choice(available_high)
                # Append one high-band item to the end; no post-append validity check.
                run_sel_idx = sel_idx + [high_idx]
                break

        if run_sel_idx is None:
            print(
                f"\nNo valid list found for run {run_number} within strict windows after {attempts} attempts.",
                flush=True,
            )
            print(
                f"Completed {len(run_selections)} of {runs} runs. "
                f"Average window: ${low_avg:.2f}–${high_avg:.2f}.",
                flush=True,
            )
            return None

        for i in run_sel_idx:
            global_names_seen.add(name_key(df.iloc[i]['Title']))
            global_skus_seen.add(df.iloc[i]['Variant Sku'])

        run_selections.append({
            "run_number": run_number,
            "selected_indices": run_sel_idx,
        })

    return build_result(df=df, run_selections=run_selections)

def send_to_webhook(payload, webhook_url=N8N_WEBHOOK_URL, timeout_seconds=10):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            response_text = resp.read().decode("utf-8", errors="replace")
            print(f"Webhook POST succeeded ({resp.status}).", flush=True)
            if response_text:
                print(f"Webhook response: {response_text}", flush=True)
            return True
    except error.URLError as exc:
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
# ==================================================================
# '''USE THE PROGRAM'''
# ==================================================================
if __name__ == "__main__":
    result = generate_random_list(
        FILE,
        DESIRED_AVG_COST_PER_ITEM,
        NUM_ITEMS_PER_RUN,
        RUNS,
        include_tags=INCLUDE_TAGS,
        exclude_tags=EXCLUDE_TAGS,
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
        send_to_webhook({
            "error": "No valid list met the strict criteria.",
            "job_id": "JOB-001",
            "items": [],
            "summary": None
        })


#{'skus': ['RSA-01130', 'RSA-04781', 'RSA-11964', 'RSA-12396', 'RSA-10445', 'RSA-05791', 'RSA-08373', 'RSA-01651', 'RSA-08131', 'RSA-03354', 'RSA-09448', 'RSA-01936', 'RSA-01828', 'RSA-11977', 'RSA-12345', 'RSA-07925', 'RSA-02768', 'RSA-00007', 'RSA-12366', 'RSA-01749', 'RSA-11451', 'RSA-12342', 'RSA-07552', 'RSA-03823', 'RSA-03034', 'RSA-01408', 'RSA-02117', 'RSA-01831', 'RSA-12385', 'RSA-06277', 'RSA-09820', 'RSA-12369', 'RSA-01153', 'RSA-03361', 'RSA-06529', 'RSA-12021', 'RSA-01377', 'RSA-08290', 'RSA-02318', 'RSA-12368', 'RSA-03352', 'RSA-01349', 'RSA-03301', 'RSA-06540', 'RSA-09936', 'RSA-05343', 'RSA-08886', 'RSA-03075', 'RSA-07012', 'RSA-06251', 'RSA-05037', 'RSA-02765', 'RSA-12288', 'RSA-10869', 'RSA-00899', 'RSA-00063', 'RSA-10737', 'RSA-12371', 'RSA-01919', 'RSA-11765', 'RSA-12393', 'RSA-10782', 'RSA-12356', 'RSA-11978', 'RSA-12446', 'RSA-11783', 'RSA-08327', 'RSA-02523', 'RSA-01198', 'RSA-04153', 'RSA-12351', 'RSA-12394', 'RSA-10082', 'RSA-03878', 'RSA-09178', 'RSA-03328', 'RSA-04328', 'RSA-04146', 'RSA-03330', 'RSA-12344', 'RSA-12183', 'RSA-06935', 'RSA-02535', 'RSA-03846', 'RSA-11853', 'RSA-12363', 'RSA-10750', 'RSA-09975', 'RSA-11976', 'RSA-10748', 'RSA-12028', 'RSA-00618', 'RSA-10450', 'RSA-10743', 'RSA-11921', 'RSA-00982', 'RSA-10741', 'RSA-11818', 'RSA-06281', 'RSA-01402', 'RSA-12310', 'RSA-12341', 'RSA-12375', 'RSA-10631', 'RSA-11984', 'RSA-00979', 'RSA-12530', 'RSA-02793', 'RSA-11400', 'RSA-00161', 'RSA-10365', 'RSA-10485', 'RSA-09211', 'RSA-04212', 'RSA-12343', 'RSA-11415', 'RSA-04300', 'RSA-00907', 'RSA-10742', 'RSA-12392', 'RSA-12372', 'RSA-02726', 'RSA-03053', 'RSA-12359', 'RSA-07456', 'RSA-10676', 'RSA-01360', 'RSA-01379', 'RSA-12395', 'RSA-10311', 'RSA-11475', 'RSA-12350', 'RSA-03899', 'RSA-11100'],
# 'avg_cost': 29.417910447761194,
# 'total_cost': 3942.0,
# 'item_count': 134,
# 'avg_price': 47.41044776119403,
# 'avg_compare_price': 66.54977611940299}
