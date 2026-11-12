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


BAG_MODES = ("Exact", "Min/Max")


def bag_requirements(gold_bag_minimum=0, green_bag_minimum=0):
    return {
        GOLD_BAG: max(0, int(gold_bag_minimum or 0)),
        GREEN_BAG: max(0, int(green_bag_minimum or 0)),
    }


def normalize_bag_maximum(maximum):
    """None means no cap."""
    if maximum is None or (isinstance(maximum, float) and pd.isna(maximum)):
        return None
    return max(0, int(maximum))


def bag_maximums(gold_bag_maximum=None, green_bag_maximum=None):
    return {
        GOLD_BAG: normalize_bag_maximum(gold_bag_maximum),
        GREEN_BAG: normalize_bag_maximum(green_bag_maximum),
    }


def bag_limits(gold_bag_minimum=0, gold_bag_maximum=None, green_bag_minimum=0, green_bag_maximum=None):
    minimums = bag_requirements(gold_bag_minimum, green_bag_minimum)
    maximums = bag_maximums(gold_bag_maximum, green_bag_maximum)
    return {group: {"min": minimums[group], "max": maximums[group]} for group in (GOLD_BAG, GREEN_BAG)}


def bag_limits_from_mode(mode, count=None, count_max=None):
    """Turn a UI mode into (minimum, maximum); maximum None means no cap.

    Min/Max: a blank minimum means 1, a blank maximum means no cap.
    """
    if mode == "Exact":
        count = max(0, int(count or 0))
        return count, count
    if mode == "Min/Max":
        minimum = 1 if count is None else max(0, int(count))
        if count_max is None:
            return minimum, None
        return minimum, max(minimum, int(count_max))
    return 0, None


def describe_bag_limit(minimum, maximum):
    if maximum is None:
        return f"at least {minimum}"
    if minimum == maximum:
        return f"exactly {minimum}"
    if minimum == 0:
        return f"at most {maximum}"
    return f"between {minimum} and {maximum}"


def bag_limit_satisfied(count, minimum, maximum):
    return count >= minimum and (maximum is None or count <= maximum)
