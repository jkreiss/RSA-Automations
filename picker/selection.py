import random
from dataclasses import dataclass

import pandas as pd

from picker.bags import GOLD_BAG, GREEN_BAG, bag_group_from_tags, bag_requirements

NFL = [
    "NCAA",
    # nfl
    "Cardinals",
    "Falcons",
    "Ravens",
    "Bills",
    "Panthers",
    "Bears",
    "Bengals",
    "Browns",
    "Cowboys",
    "Broncos",
    "Lions",
    "Packers",
    "Texans",
    "Colts",
    "Jaguars",
    "Chiefs",
    "Raiders",
    "Chargers",
    "Rams",
    "Dolphins",
    "Vikings",
    "Patriots",
    "Saints",
    "Giants",
    "Jets",
    "Eagles",
    "Steelers",
    "49ers",
    "Seahawks",
    "Buccaneers",
    "Titans",
    "Commanders",]
NHL = [
# nhl
    "Avalanche",
    "Blackhawks",
    "Blue Jackets",
    "Blues",
    "Bruins",
    "Canadiens",
    "Canucks",
    "Capitals",
    "Coyotes",
    "Devils",
    "Ducks",
    "Flames",
    "Flyers",
    "Golden Knights",
    "Hurricanes",
    "Islanders",
    "Jets",
    "Kings",
    "Kraken",
    "Lightning",
    "Maple Leafs",
    "Oilers",
    "Panthers",
    "Penguins",
    "Predators",
    "Rangers",
    "Red Wings",
    "Sabres",
    "Senators",
    "Sharks",
    "Stars",
    "Wild",
]
MLB = [
# mlb
    "Angels",
    "Astros",
    "Athletics",
    "Blue Jays",
    "Braves",
    "Brewers",
    "Cardinals",
    "Cubs",
    "Diamondbacks",
    "Dodgers",
    "Giants",
    "Guardians",
    "Mariners",
    "Marlins",
    "Mets",
    "Nationals",
    "Orioles",
    "Padres",
    "Phillies",
    "Pirates",
    "Rangers",
    "Rays",
    "Red Sox",
    "Reds",
    "Rockies",
    "Royals",
    "Tigers",
    "Twins",
    "White Sox",
    "Yankees",
]
NBA= [
    # nba
    "76ers",
    "Bucks",
    "Bulls",
    "Cavaliers",
    "Celtics",
    "Clippers",
    "Grizzlies",
    "Hawks",
    "Heat",
    "Hornets",
    "Jazz",
    "Kings",
    "Knicks",
    "Lakers",
    "Magic",
    "Mavericks",
    "Nets",
    "Nuggets",
    "Pacers",
    "Pelicans",
    "Pistons",
    "Raptors",
    "Rockets",
    "Spurs",
    "Suns",
    "Thunder",
    "Timberwolves",
    "Trail Blazers",
    "Warriors",
    "Wizards",
]

LEAGUE_TEAMS = {
    "NFL": NFL,
    "NHL": NHL,
    "MLB": MLB,
    "NBA": NBA,
}
ALL_LEAGUES = list(LEAGUE_TEAMS)
TEAMS = [team for league_teams in LEAGUE_TEAMS.values() for team in league_teams]

@dataclass
class SelectionResult:
    selected_df: pd.DataFrame
    attempt_number: int
    min_items: int
    max_items: int
    low_avg: float
    high_avg: float


def select_items(df, config):
    df = in_stock_items(df).reset_index(drop=True)
    if df.empty:
        return None

    rng = random.Random(config.seed)

    number_tolerance = max(0, int(round(config.num_items * config.count_variance)))
    required_bag_count = sum(configured_bag_requirements(config).values())
    min_items = max(1, config.num_items - number_tolerance, required_bag_count)
    requested_max_items = config.num_items + number_tolerance
    available_capacity = selection_capacity(df, config)
    max_items = min(available_capacity, requested_max_items)
    low_avg = config.desired_avg_cost_per_item * (1 - config.avg_tolerance)
    high_avg = config.desired_avg_cost_per_item * (1 + config.avg_tolerance)

    if min_items > max_items:
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
    team_key = team_key_mapper(config)
    groups = df["Tags"].map(bag_group_from_tags).tolist()
    requirements = configured_bag_requirements(config)
    # initial selection pseudo random
    if config.allow_duplicates:
        selected_indices = []
        selected_sku_counts = {}
        sku_inventory = inventory_by_sku(df)
        team_keys = df["Tags"].map(team_key).tolist()
        selected_team_counts = {}
        team_limit = team_duplicate_limit_count(config, target_count)

        for group in (GOLD_BAG, GREEN_BAG):
            while count_selected_bags(selected_indices, groups).get(group, 0) < requirements[group]:
                candidates = [
                    index for index, row in df.iterrows()
                    if groups[index] == group
                    and selected_sku_counts.get(row["Variant Sku"], 0) < sku_inventory.get(row["Variant Sku"], 0)
                    and can_add_team(index, team_keys, selected_team_counts, team_limit)
                ]
                if not candidates:
                    return []

                index = rng.choice(candidates)
                sku = df.iloc[index]["Variant Sku"]
                selected_sku_counts[sku] = selected_sku_counts.get(sku, 0) + 1
                increment_team_count(index, team_keys, selected_team_counts)
                selected_indices.append(index)

        while len(selected_indices) < target_count:
            candidates = [
                index for index, row in df.iterrows()
                if selected_sku_counts.get(row["Variant Sku"], 0) < sku_inventory.get(row["Variant Sku"], 0)
                and can_add_team(index, team_keys, selected_team_counts, team_limit)
            ]
            if not candidates:
                break

            index = rng.choice(candidates)
            sku = df.iloc[index]["Variant Sku"]
            selected_sku_counts[sku] = selected_sku_counts.get(sku, 0) + 1
            increment_team_count(index, team_keys, selected_team_counts)
            selected_indices.append(index)

        return selected_indices

    selected_indices = []
    names_seen = set()
    skus_seen = set()
    team_keys = df["Tags"].map(team_key).tolist()
    selected_team_counts = {}
    team_limit = team_duplicate_limit_count(config, target_count)

    for group in (GOLD_BAG, GREEN_BAG):
        order = [index for index in range(len(df)) if groups[index] == group]
        rng.shuffle(order)
        for index in order:
            if count_selected_bags(selected_indices, groups).get(group, 0) >= requirements[group]:
                break
            row = df.iloc[index]
            if int(row.get('Variant Inventory Qty', 1)) <= 0:
                continue
            name = name_key(row["Title"])
            sku = row["Variant Sku"]
            if name not in names_seen and sku not in skus_seen and can_add_team(index, team_keys, selected_team_counts, team_limit):
                names_seen.add(name)
                skus_seen.add(sku)
                increment_team_count(index, team_keys, selected_team_counts)
                selected_indices.append(index)
        if count_selected_bags(selected_indices, groups).get(group, 0) < requirements[group]:
            return []

    order = list(range(len(df)))
    rng.shuffle(order)

    for index in order:
        if len(selected_indices) >= target_count:
            break

        row = df.iloc[index]
        if int(row.get('Variant Inventory Qty', 1)) <= 0:
            continue

        name = name_key(row["Title"])
        sku = row["Variant Sku"]

        if name not in names_seen and sku not in skus_seen and can_add_team(index, team_keys, selected_team_counts, team_limit):
            names_seen.add(name)
            skus_seen.add(sku)
            increment_team_count(index, team_keys, selected_team_counts)
            selected_indices.append(index)

    return selected_indices


def improve_selection(df, config, selected_indices, target_avg, low_avg, high_avg, swap_tries, target_count, rng):
    team_key = team_key_mapper(config)
    pool_idx = set(range(len(df)))
    if not config.allow_duplicates:
        pool_idx -= set(selected_indices)
    costs = df['Cost Per Item'].to_numpy()
    name_keys = df["Title"].map(name_key).tolist()
    skus = df["Variant Sku"].tolist()
    sku_inventory = inventory_by_sku(df)
    team_keys = df["Tags"].map(team_key).tolist()
    selected_team_counts = count_selected_teams(selected_indices, team_keys)
    team_limit = team_duplicate_limit_count(config, target_count)
    bag_groups = df["Tags"].map(bag_group_from_tags).tolist()
    selected_bag_counts = count_selected_bags(selected_indices, bag_groups)
    requirements = configured_bag_requirements(config)

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
        if not can_swap_without_exceeding_team_limit(out_i, in_i, team_keys, selected_team_counts, team_limit):
            continue
        if not can_swap_without_violating_bag_minimum(
            out_i,
            in_i,
            bag_groups,
            selected_bag_counts,
            requirements,
        ):
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
            update_team_counts_after_swap(out_i, in_i, team_keys, selected_team_counts)
            update_bag_counts_after_swap(out_i, in_i, bag_groups, selected_bag_counts)

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


def in_stock_items(df):
    return df[df['Variant Inventory Qty'] > 0]


def num_unique_items(df):
    in_stock_df = in_stock_items(df)
    return min(len(in_stock_df), in_stock_df["Title"].map(name_key).nunique(), in_stock_df["Variant Sku"].nunique())


def inventory_by_sku(df):
    in_stock_df = in_stock_items(df)
    return in_stock_df.groupby("Variant Sku")['Variant Inventory Qty'].max().astype(int).to_dict()


def selection_capacity(df, config):
    if config.allow_duplicates:
        return int(sum(inventory_by_sku(df).values()))
    return num_unique_items(df)


def configured_bag_requirements(config):
    return bag_requirements(
        getattr(config, "gold_bag_minimum", 0),
        getattr(config, "green_bag_minimum", 0),
    )


def bag_capacity_by_group(df, config):
    capacities = {}
    groups = df["Tags"].map(bag_group_from_tags)
    for group in (GOLD_BAG, GREEN_BAG):
        group_df = df[groups == group]
        capacities[group] = selection_capacity(group_df, config) if not group_df.empty else 0
    return capacities


def count_selected_bags(selected_indices, bag_groups):
    counts = {GOLD_BAG: 0, GREEN_BAG: 0}
    for index in selected_indices:
        group = bag_groups[index]
        if group in counts:
            counts[group] += 1
    return counts


def can_swap_without_violating_bag_minimum(out_i, in_i, bag_groups, selected_counts, requirements):
    out_group = bag_groups[out_i]
    in_group = bag_groups[in_i]
    if out_group == in_group or out_group not in requirements:
        return True
    return selected_counts.get(out_group, 0) > requirements[out_group]


def update_bag_counts_after_swap(out_i, in_i, bag_groups, selected_counts):
    out_group = bag_groups[out_i]
    in_group = bag_groups[in_i]
    if out_group == in_group:
        return
    if out_group in selected_counts:
        selected_counts[out_group] -= 1
    if in_group in selected_counts:
        selected_counts[in_group] += 1


def count_selected_skus(selected_indices, skus):
    counts = {}
    for index in selected_indices:
        sku = skus[index]
        counts[sku] = counts.get(sku, 0) + 1
    return counts


def team_duplicate_limit_count(config, target_count):
    if not config.limit_team_duplicates:
        return None

    limit = float(config.team_duplicates_limit)
    if limit > 1:
        limit = limit / 100
    if limit <= 0:
        return 0

    return max(1, int(target_count * limit))


def count_selected_teams(selected_indices, team_keys):
    counts = {}
    for index in selected_indices:
        increment_team_count(index, team_keys, counts)
    return counts


def can_add_team(index, team_keys, selected_team_counts, team_limit):
    if team_limit is None:
        return True

    team = team_keys[index]
    if is_missing_team_key(team):
        return True

    return selected_team_counts.get(team, 0) < team_limit


def can_swap_without_exceeding_team_limit(out_i, in_i, team_keys, selected_team_counts, team_limit):
    if team_limit is None:
        return True

    out_team = team_keys[out_i]
    in_team = team_keys[in_i]
    if is_missing_team_key(in_team) or in_team == out_team:
        return True

    return selected_team_counts.get(in_team, 0) < team_limit


def increment_team_count(index, team_keys, selected_team_counts):
    team = team_keys[index]
    if not is_missing_team_key(team):
        selected_team_counts[team] = selected_team_counts.get(team, 0) + 1


def update_team_counts_after_swap(out_i, in_i, team_keys, selected_team_counts):
    out_team = team_keys[out_i]
    in_team = team_keys[in_i]
    if out_team == in_team:
        return

    if not is_missing_team_key(out_team):
        next_count = selected_team_counts.get(out_team, 0) - 1
        if next_count > 0:
            selected_team_counts[out_team] = next_count
        else:
            selected_team_counts.pop(out_team, None)

    if not is_missing_team_key(in_team):
        selected_team_counts[in_team] = selected_team_counts.get(in_team, 0) + 1


def is_missing_team_key(team):
    return team is None or pd.isna(team)


def can_swap_without_exceeding_inventory(out_i, in_i, skus, selected_sku_counts, sku_inventory):
    out_sku = skus[out_i]
    in_sku = skus[in_i]
    if out_sku == in_sku:
        return True
    return selected_sku_counts.get(in_sku, 0) < sku_inventory.get(in_sku, 0)


def team_key_mapper(config):
    leagues = getattr(config, "leagues", None)
    return lambda tags: team_key_from_tags(tags, leagues)


def teams_for_leagues(leagues=None):
    if not leagues:
        return TEAMS

    teams = []
    for league in leagues:
        teams.extend(LEAGUE_TEAMS.get(league, []))
    return teams


def selected_leagues_for(leagues=None):
    if not leagues:
        return ALL_LEAGUES
    return [league for league in leagues if league in LEAGUE_TEAMS]


def matches_selected_leagues(tags, leagues=None):
    if not leagues:
        return True

    selected_leagues = selected_leagues_for(leagues)
    if not selected_leagues:
        return False

    tag_values = {tag.strip().lower() for tag in str(tags).split(",")}
    explicitly_tagged_leagues = [
        league for league in ALL_LEAGUES if league.lower() in tag_values
    ]
    if explicitly_tagged_leagues:
        return any(league in selected_leagues for league in explicitly_tagged_leagues)

    return any(
        team.lower() in tag_values
        for league in selected_leagues
        for team in LEAGUE_TEAMS[league]
    )


def team_key_from_tags(tags, leagues=None):
    tag_values = {tag.strip().lower() for tag in str(tags).split(",")}

    selected_leagues = selected_leagues_for(leagues)
    all_tagged_leagues = [league for league in ALL_LEAGUES if league.lower() in tag_values]
    tagged_leagues = [league for league in selected_leagues if league.lower() in tag_values]
    if all_tagged_leagues and not tagged_leagues:
        return None
    leagues_to_check = tagged_leagues or selected_leagues

    for league in leagues_to_check:
        for team in LEAGUE_TEAMS[league]:
            if team.lower() in tag_values:
                return team

    return None
