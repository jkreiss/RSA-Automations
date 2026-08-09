# from picker.runs import (
#     ATTEMPTS,
#     AVG_TOLERANCE,
#     COST_VARIANCE,
#     COUNT_VARIANCE,
#     DESIRED_AVG_COST_PER_ITEM,
#     EXCLUDE_TAGS,
#     EXCLUDE_TYPES,
#     FILE,
#     INCLUDE_TAGS,
#     INCLUDE_TYPES,
#     MAXIMUM_COST,
#     MINIMUM_COST,
#     N8N_WEBHOOK_URL,
#     NUM_ITEMS,
#     RANDOM_SEED,
#     SWAP_TRIES,
#     generate_random_list,
# )
# from picker.logging_utils import emit_message, generate_job_id, get_log_file, get_logger, log_event
# from picker.webhook import send_to_webhook
#
#
# if __name__ == "__main__":
#     result = generate_random_list(
#         FILE,
#         DESIRED_AVG_COST_PER_ITEM,
#         NUM_ITEMS,
#         minimum_cost=MINIMUM_COST,
#         maximum_cost=MAXIMUM_COST,
#         count_variance=COUNT_VARIANCE,
#         avg_tolerance=AVG_TOLERANCE,
#         attempts=ATTEMPTS,
#         swap_tries=SWAP_TRIES,
#         seed=RANDOM_SEED,
#     )
#
#     if result:
#         print(result)
#         send_to_webhook(result)
#     else:
#         print("\nProgram terminated: No valid list met the strict criteria.", flush=True)
