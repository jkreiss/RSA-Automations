from dataclasses import dataclass

from picker.selection import name_key, selection_capacity


@dataclass
class SelectionStats:
    unique_players: int
    unique_skus: int
    unique_capacity: int
    min_items: int
    max_items: int
    low_avg: float
    high_avg: float
    pool_avg: float
    pool_min_cost: float
    pool_max_cost: float
    best_possible_avg: float | None
    count_possible: bool
    avg_possible_for_requested_count: bool


def calculate_selection_stats(df, config):
    if df.empty:
        number_tolerance = max(0, int(round(config.num_items * config.count_variance)))
        min_items = max(1, config.num_items - number_tolerance)
        max_items = config.num_items + number_tolerance
        low_avg = config.desired_avg_cost_per_item * (1 - config.avg_tolerance)
        high_avg = config.desired_avg_cost_per_item * (1 + config.avg_tolerance)
        return SelectionStats(
            unique_players=0,
            unique_skus=0,
            unique_capacity=0,
            min_items=min_items,
            max_items=max_items,
            low_avg=low_avg,
            high_avg=high_avg,
            pool_avg=0.0,
            pool_min_cost=0.0,
            pool_max_cost=0.0,
            best_possible_avg=None,
            count_possible=False,
            avg_possible_for_requested_count=False,
        )

    df = df.reset_index(drop=True)
    number_tolerance = max(0, int(round(config.num_items * config.count_variance)))
    min_items = max(1, config.num_items - number_tolerance)
    requested_max_items = config.num_items + number_tolerance
    max_items = min(selection_capacity(df, config), requested_max_items)
    low_avg = config.desired_avg_cost_per_item * (1 - config.avg_tolerance)
    high_avg = config.desired_avg_cost_per_item * (1 + config.avg_tolerance)

    in_stock_df = df[df['Variant Inventory Qty'] > 0]
    unique_title_keys = in_stock_df["Title"].map(name_key).nunique()
    unique_skus = in_stock_df["Variant Sku"].nunique()
    unique_capacity = selection_capacity(df, config)

    best_unique_df = best_unique_items_by_cost(df, config.num_items)
    best_possible_count = len(best_unique_df)
    best_possible_avg = float(best_unique_df["Cost Per Item"].mean()) if best_possible_count else None



    return SelectionStats(
        unique_players=int(unique_title_keys),
        unique_skus=int(unique_skus),
        unique_capacity=int(unique_capacity),
        min_items=min_items,
        max_items=max_items,
        low_avg=float(low_avg),
        high_avg=float(high_avg),
        pool_avg=float(df["Cost Per Item"].mean()),
        pool_min_cost=float(df["Cost Per Item"].min()),
        pool_max_cost=float(df["Cost Per Item"].max()),
        best_possible_avg=best_possible_avg,
        count_possible=min_items <= unique_capacity,
        avg_possible_for_requested_count=(
            best_possible_count >= config.num_items
            and best_possible_avg is not None
            and low_avg <= best_possible_avg <= high_avg
        ),
    )


def best_unique_items_by_cost(df, limit):
    selected_indices = []
    names_seen = set()
    skus_seen = set()

    for index, row in df.sort_values("Cost Per Item", ascending=False).iterrows():
        if int(row.get('Variant Inventory Qty', 1)) <= 0:
            continue
        name = name_key(row["Title"])
        sku = row["Variant Sku"]
        if name in names_seen or sku in skus_seen:
            continue

        names_seen.add(name)
        skus_seen.add(sku)
        selected_indices.append(index)

        if len(selected_indices) >= limit:
            break

    return df.loc[selected_indices]
