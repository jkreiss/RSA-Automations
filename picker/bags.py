import pandas as pd


GOLD_BAG = "GOLD BAG"
GREEN_BAG = "GREEN BAG"
UNTAGGED = "UNTAGGED"
BAG_GROUPS = (GOLD_BAG, GREEN_BAG, UNTAGGED)
BAG_SORT_ORDER = {group: position for position, group in enumerate(BAG_GROUPS)}


def normalized_tags(tags):
    if tags is None or pd.isna(tags):
        return set()
    return {value.strip().casefold() for value in str(tags).split(",") if value.strip()}


def bag_group_from_tags(tags):
    tags_set = normalized_tags(tags)
    if GOLD_BAG.casefold() in tags_set:
        return GOLD_BAG
    if GREEN_BAG.casefold() in tags_set:
        return GREEN_BAG
    return UNTAGGED


def pick_list_name(title):
    words = str(title or "").split()
    if len(words) >= 2:
        return f"{words[1]} {words[0]}"
    return words[0] if words else ""


def bag_requirements(gold_bag_minimum=0, green_bag_minimum=0):
    return {
        GOLD_BAG: max(0, int(gold_bag_minimum or 0)),
        GREEN_BAG: max(0, int(green_bag_minimum or 0)),
    }
