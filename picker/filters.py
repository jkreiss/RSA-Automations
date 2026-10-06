import pandas as pd

from picker.bags import GOLD_BAG, bag_group_from_tags
from picker.config import PickerConfig
from picker.selection import matches_selected_leagues

def filter_df(df , config):
    # Tags should be and i.e. if [inhouse, sale] then item must fulfill inhouse AND sale
    # Type should be or i.e. if [football, jersey] then item must be typed football OR jersey
    # Most likely used with only one type at a time anyway

    # Both together: item must have every tag AND match at least one type

    if config.include_tags:
        tag_mask = pd.Series(True, index=df.index)
        for tag in config.include_tags:
            # NOTE: substring + case-sensitive match, so "NFC" also matches "NFC NORTH"
            # and "football" won't match "Football"
            tag_mask &= df['Tags'].str.contains(tag, na=False, regex=True)
        df = df[tag_mask]

    if config.include_types:
        type_mask = pd.Series(False, index=df.index)
        for type_val in config.include_types:
            type_mask |= df['Type'].str.contains(type_val, na=False, regex=True)
        df = df[type_mask]

    if config.exclude_tags:
        for tag in config.exclude_tags:
            if tag:
                df = df[~df['Tags'].str.contains(tag, na=False, regex=True)]

    if config.exclude_types:
        for type_val in config.exclude_types:
            if type_val:
                df = df[~df['Type'].str.contains(type_val, na=False, regex=True)]

    if config.leagues:
        df = df[df['Tags'].map(lambda tags: matches_selected_leagues(tags, config.leagues))]

    # return filtered df between min and max costs
    cost_mask = df['Cost Per Item'].between(config.resolved_minimum_cost, config.resolved_maximum_cost)
    if config.gold_bag_minimum > 0:
        # gold bag items may exceed the maximum cost; every other filter still applies
        is_gold = df['Tags'].map(bag_group_from_tags) == GOLD_BAG
        cost_mask |= is_gold & (df['Cost Per Item'] >= config.resolved_minimum_cost)
    df = df[cost_mask]
    return df
