import random
from dataclasses import dataclass

import pandas as pd

@dataclass
class SelectionResult:
    selected_df: pd.DataFrame
    attempt_number: int
    min_items: int
    max_items: int
    low_avg: float
    high_avg: float


def select_items(df, config):
    if df.empty:
        return None

    df = df.reset_index(drop=True)
    rng = random.Random(config.seed)

    number_tolerance = max(0, int(round(config.num_items * config.count_variance)))
    min_items = max(1, config.num_items - number_tolerance)
    requested_max_items = config.num_items + number_tolerance
    available_capacity = selection_capacity(df, config)
    max_items = min(available_capacity, requested_max_items)
    low_avg = config.desired_avg_cost_per_item * (1 - config.avg_tolerance)
    high_avg = config.desired_avg_cost_per_item * (1 + config.avg_tolerance)

    if min_items > available_capacity:
        return None

    for attempt_number in range(1, config.attempts + 1):
        target_count = rng.randint(min_items, max_items)
        selected_indices = initial_selection(df, config, target_count, rng)

        if len(selected_indices) < target_count:
            continue
        current_avg = df["Cost Per Item"].iloc[selected_indices].mean()

        if not low_avg <= current_avg <= high_avg:
            selected_indices = improve_selection(
                df=df,
                config=config,
                selected_indices=selected_indices,
                target_avg=config.desired_avg_cost_per_item,
                low_avg=low_avg,
                high_avg=high_avg,
                swap_tries=config.swap_tries,
                target_count=target_count,
                rng=rng,
            )

        selected_df = df.iloc[selected_indices]
        avg_cost = selected_df["Cost Per Item"].mean()

        if min_items <= len(selected_df) <= max_items and low_avg <= avg_cost <= high_avg:
            return SelectionResult(
                selected_df=selected_df,
                attempt_number=attempt_number,
                min_items=min_items,
                max_items=max_items,
                low_avg=low_avg,
                high_avg=high_avg,
            )

    return None


def name_key(title):
    return ' '.join(str(title).split()[:2])


def initial_selection(df, config, target_count, rng):
    # initial selection pseudo random
    if config.allow_duplicates:
        selected_indices = []
        selected_sku_counts = {}
        sku_inventory = inventory_by_sku(df)

        while len(selected_indices) < target_count:
            candidates = [
                index
                for index, row in df.iterrows()
                if selected_sku_counts.get(row["Variant Sku"], 0) < sku_inventory.get(row["Variant Sku"], 0)
            ]
            if not candidates:
                break

            index = rng.choice(candidates)
            sku = df.iloc[index]["Variant Sku"]
            selected_sku_counts[sku] = selected_sku_counts.get(sku, 0) + 1
            selected_indices.append(index)

        return selected_indices

    order = list(range(len(df)))
    rng.shuffle(order)

    selected_indices = []
    names_seen = set()
    skus_seen = set()

    for index in order:
        if len(selected_indices) >= target_count:
            break

        row = df.iloc[index]
        if int(row.get('Variant Inventory Qty', 1)) <= 0:
            continue

        name = name_key(row["Title"])
        sku = row["Variant Sku"]

        if config.allow_duplicates or (name not in names_seen and sku not in skus_seen):
            names_seen.add(name)
            skus_seen.add(sku)
            selected_indices.append(index)

    return selected_indices


def improve_selection(df, config, selected_indices, target_avg, low_avg, high_avg, swap_tries, target_count, rng):
    pool_idx = set(range(len(df)))
    if not config.allow_duplicates:
        pool_idx -= set(selected_indices)
    costs = df['Cost Per Item'].to_numpy()
    name_keys = df["Title"].map(name_key).tolist()
    skus = df["Variant Sku"].tolist()
    sku_inventory = inventory_by_sku(df)

    low_pool = [i for i in pool_idx if costs[i] <= target_avg]
    high_pool = [i for i in pool_idx if costs[i] > target_avg]

    sel_low_idx = [i for i in selected_indices if costs[i] <= target_avg]
    sel_high_idx = [i for i in selected_indices if costs[i] > target_avg]

    selected_names = {name_keys[i] for i in selected_indices}
    selected_skus = {skus[i] for i in selected_indices}
    selected_sku_counts = count_selected_skus(selected_indices, skus)
    total = float(costs[selected_indices].sum())

    for _ in range(swap_tries):
        cur_avg = total / target_count # this is k
        need_up = (cur_avg < target_avg)

        if need_up and sel_low_idx and high_pool:
            out_i = rng.choice(sel_low_idx)
            in_i = rng.choice(high_pool)
        elif (not need_up) and sel_high_idx and low_pool:
            out_i = rng.choice(sel_high_idx)
            in_i = rng.choice(low_pool)
        else:
            if not pool_idx:
                break
            out_i = rng.choice(selected_indices)
            in_i = rng.choice(list(pool_idx))

        # check first two words + SKU
        if not config.allow_duplicates:
            out_name = name_keys[out_i]
            in_name = name_keys[in_i]
            out_sku = skus[out_i]
            in_sku = skus[in_i]

            if (in_name != out_name and in_name in selected_names) or (in_sku != out_sku and in_sku in selected_skus):
                continue
        elif not can_swap_without_exceeding_inventory(out_i, in_i, skus, selected_sku_counts, sku_inventory):
            continue

        new_total = total - costs[out_i] + costs[in_i]
        new_avg = new_total / target_count
        if abs(new_avg - target_avg) < abs(cur_avg - target_avg):
            # commit swap
            total = new_total
            selected_indices[selected_indices.index(out_i)] = in_i  # replace one position

            if not config.allow_duplicates:
                selected_names.discard(name_keys[out_i])
                selected_names.add(name_keys[in_i])
                selected_skus.discard(skus[out_i])
                selected_skus.add(skus[in_i])
                pool_idx.remove(in_i)
                pool_idx.add(out_i)
            else:
                # decrement
                next_count = selected_sku_counts.get(skus[out_i], 0) - 1
                if next_count > 0:
                    selected_sku_counts[skus[out_i]] = next_count
                else:
                    selected_sku_counts.pop(skus[out_i], None)
                selected_sku_counts[skus[in_i]] = selected_sku_counts.get(skus[in_i], 0) + 1

            if not config.allow_duplicates:
                if in_i in low_pool:
                    low_pool.remove(in_i)
                if in_i in high_pool:
                    high_pool.remove(in_i)
            if costs[out_i] <= target_avg:
                if out_i in sel_low_idx:
                    sel_low_idx.remove(out_i)
                if not config.allow_duplicates:
                    low_pool.append(out_i)
            else:
                if out_i in sel_high_idx:
                    sel_high_idx.remove(out_i)
                if not config.allow_duplicates:
                    high_pool.append(out_i)

            if costs[in_i] <= target_avg:
                sel_low_idx.append(in_i)
            else:
                sel_high_idx.append(in_i)

            if low_avg <= new_avg <= high_avg:
                break

    return selected_indices


def num_unique_items(df):
    in_stock_df = df[df['Variant Inventory Qty'] > 0]
    return min(len(in_stock_df), in_stock_df["Title"].map(name_key).nunique(), in_stock_df["Variant Sku"].nunique())


def inventory_by_sku(df):
    return df.groupby("Variant Sku")['Variant Inventory Qty'].max().astype(int).to_dict()


def selection_capacity(df, config):
    if config.allow_duplicates:
        return int(sum(inventory_by_sku(df).values()))
    return num_unique_items(df)


def count_selected_skus(selected_indices, skus):
    counts = {}
    for index in selected_indices:
        sku = skus[index]
        counts[sku] = counts.get(sku, 0) + 1
    return counts


def can_swap_without_exceeding_inventory(out_i, in_i, skus, selected_sku_counts, sku_inventory):
    out_sku = skus[out_i]
    in_sku = skus[in_i]
    if out_sku == in_sku:
        return True
    return selected_sku_counts.get(in_sku, 0) < sku_inventory.get(in_sku, 0)


