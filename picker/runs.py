from picker import csvhelper, filters, results, selection, selection_stats
from picker.config import DEFAULT_WEBHOOK_URL, PickerConfig
from picker.csvhelper import CSVLoadError
from picker.logging_utils import generate_job_id, log_event


FILE = "spreadsheets/products_export_1 (9).csv"
DESIRED_AVG_COST_PER_ITEM = 44
NUM_ITEMS = 100

INCLUDE_TAGS = [""]
EXCLUDE_TAGS = [""]
INCLUDE_TYPES = [""]
EXCLUDE_TYPES = [""]

MINIMUM_COST = 0.0
MAXIMUM_COST = 0.0

COUNT_VARIANCE = 0.0
AVG_TOLERANCE = 0.10
COST_VARIANCE = 1.5
ATTEMPTS = 1
SWAP_TRIES = 800
RANDOM_SEED = None
N8N_WEBHOOK_URL = DEFAULT_WEBHOOK_URL


def fail_run(job_id, code, message, *, details=None, stats=None):
    stats_payload = results.serialize_selection_stats(stats)
    log_event(
        "automation_failed",
        level="error",
        job_id=job_id,
        reason=code,
        message=message,
        details=details or {},
        selection_stats=stats_payload,
    )
    return results.build_failure_payload(
        job_id=job_id,
        code=code,
        message=message,
        details=details,
        selection_stats=stats_payload,
    )


def generate_random_list(
    filename=FILE,
    desired_avg_cost_per_item=DESIRED_AVG_COST_PER_ITEM,
    num_items=NUM_ITEMS,
    minimum_cost=MINIMUM_COST,
    maximum_cost=MAXIMUM_COST,
    include_tags=None,
    exclude_tags=None,
    include_types=None,
    exclude_types=None,
    count_variance=COUNT_VARIANCE,
    avg_tolerance=AVG_TOLERANCE,
    attempts=ATTEMPTS,
    cost_variance=COST_VARIANCE,
    swap_tries=SWAP_TRIES,
    seed=RANDOM_SEED,
    job_id=None,
    emails=None,
    allow_duplicates=True,
):
    include_tags = INCLUDE_TAGS if include_tags is None else include_tags
    exclude_tags = EXCLUDE_TAGS if exclude_tags is None else exclude_tags
    include_types = INCLUDE_TYPES if include_types is None else include_types
    exclude_types = EXCLUDE_TYPES if exclude_types is None else exclude_types
    job_id = job_id or generate_job_id()
    emails = results.normalize_emails(emails)

    log_event(
        "automation_started",
        job_id=job_id,
        filename=filename,
        desired_avg_cost_per_item=desired_avg_cost_per_item,
        num_items=num_items,
        minimum_cost=minimum_cost,
        maximum_cost=maximum_cost,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        include_types=include_types,
        exclude_types=exclude_types,
        count_variance=count_variance,
        avg_tolerance=avg_tolerance,
        attempts=attempts,
        cost_variance=cost_variance,
        swap_tries=swap_tries,
        seed=seed,
        emails=emails,
    )

    picker_config = PickerConfig(
        desired_avg_cost_per_item=desired_avg_cost_per_item,
        num_items=num_items,
        minimum_cost=minimum_cost,
        maximum_cost=maximum_cost,
        include_tags=[tag for tag in include_tags if tag],
        exclude_tags=[tag for tag in exclude_tags if tag],
        include_types=[type_val for type_val in include_types if type_val],
        exclude_types=[type_val for type_val in exclude_types if type_val],
        count_variance=count_variance,
        avg_tolerance=avg_tolerance,
        attempts=attempts,
        cost_variance=cost_variance,
        swap_tries=swap_tries,
        seed=seed,
        allow_duplicates=allow_duplicates,
        emails=None,
    )

    try:
        df = csvhelper.load_csv(filename)
    except CSVLoadError as exc:
        return fail_run(
            job_id=job_id,
            code="csv_load_failed",
            message=str(exc),
            details={"error": str(exc)},
        )

    df = filters.filter_df(df, picker_config)
    if df.empty:
        stats = selection_stats.calculate_selection_stats(df, picker_config)
        return fail_run(
            job_id=job_id,
            code="no_matching_items",
            message="No items match your filters. Please adjust your criteria.",
            stats=stats,
        )

    selection_result = selection.select_items(df, picker_config)
    if selection_result is None:
        stats = selection_stats.calculate_selection_stats(df, picker_config)
        return fail_run(
            job_id=job_id,
            code="no_valid_list_found",
            message="No valid list found matching criteria.",
            details={
                "attempts": attempts,
                "actual_cost_mean": float(df["Cost Per Item"].mean()),
            },
            stats=stats,
        )

    candidate = results.build_result_from_selection(selection_result, job_id=job_id, emails=emails)
    log_event(
        "automation_succeeded",
        job_id=job_id,
        attempt_number=selection_result.attempt_number,
        item_count=candidate["summary"]["item_count"],
        avg_cost=candidate["summary"]["avg_cost"],
        total_cost=candidate["summary"]["total_cost"],
    )
    return candidate
