from picker.config import PickerConfig
import pandas as pd

def filter_df(df , config):
    # Tags should be and i.e. if [inhouse, sale] then item must fulfill inhouse AND sale
    # Type should be or i.e. if [football, jersey] then item must be typed football OR jersey
    # Most likely used with only one type at a time anyway

    if config.include_tags and config.include_types:
        mask = pd.Series(False, index=df.index)
        for tag in config.include_tags:
            mask &= df['Tags'].str.contains(tag, na=False, regex=True)
        for type_val in config.include_types:
            mask |= df['Type'].str.contains(type_val, na=False, regex=True)
        df = df[mask]

    elif config.include_tags:
        tag_mask = pd.Series(False, index=df.index)
        for tag in config.include_tags:
            tag_mask &= df['Tags'].str.contains(tag, na=False, regex=True)
        df = df[tag_mask]

    elif config.include_types:
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

    # return filtered df between min and max costs
    df = df[df['Cost Per Item'].between(config.resolved_minimum_cost, config.resolved_maximum_cost)]
    return df
