import copy
import tempfile

import pandas as pd
import streamlit as st

from picker import csvhelper, filters, review
from picker import results as picker_results
from picker.config import PickerConfig
from picker.invoice_counter import InvoiceCounterError, ensure_invoice_id
from picker.logging_utils import generate_job_id, log_event
from picker.runs import (
    ATTEMPTS,
    AVG_TOLERANCE,
    COST_VARIANCE,
    COUNT_VARIANCE,
    DESIRED_AVG_COST_PER_ITEM,
    EXCLUDE_TAGS,
    EXCLUDE_TYPES,
    INCLUDE_TAGS,
    INCLUDE_TYPES,
    LIMIT_TEAM_DUPLICATES,
    MAXIMUM_COST,
    MINIMUM_COST,
    NUM_ITEMS,
    TEAM_DUPLICATES_LIMIT,
    generate_random_list,
)
from picker.selection import ALL_LEAGUES
from picker.webhook import send_to_webhook


def build_email_payload(mode: str, shared_email: str, pick_email: str, listing_email: str, invoice_email: str):
    if mode == "No email":
        return {"pick": "", "listing": "", "invoice": ""}

    if mode == "One email for all lists":
        email = shared_email.strip()
        return {"pick": email, "listing": email, "invoice": email}

    return {
        "pick": pick_email.strip(),
        "listing": listing_email.strip(),
        "invoice": invoice_email.strip(),
    }


def format_money(value):
    return "" if value is None else f"\${value:.2f}"


def build_selection_stats_table(stats):
    if not stats:
        return None

    rows = [
        ("Unique Player Titles", stats["unique_players"]),
        ("Unique SKUs", stats["unique_skus"]),
        ("Number of items that can be chosen from", stats["unique_capacity"]),
        ("Maximum GOLD BAG Items", stats["max_gold_bag_items"]),
        ("Maximum GREEN BAG Items", stats["max_green_bag_items"]),
        ("Average cost with parameters", format_money(stats["best_possible_avg"])),
        ("Allowed Item Range", f"{stats['min_items']} - {stats['max_items']}"),
        ("Allowed Average Range", f"\${stats['low_avg']:.2f} - ${stats['high_avg']:.2f}"),
        ("Pool Average Cost", format_money(stats["pool_avg"])),
        ("Pool Min/Max Costs", f"\${stats['pool_min_cost']:.2f} - ${stats['pool_max_cost']:.2f}"),
        ("Enough Items", "Yes" if stats["count_possible"] else "No"),
        ("Average Possible For Requested Count", "Yes" if stats["avg_possible_for_requested_count"] else "No"),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def build_team_counts_table(team_counts):
    if not team_counts:
        return None

    rows = [
        {"Team": team, "Count": count}
        for team, count in sorted(team_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return pd.DataFrame(rows)


def render_generation_failure(failure):
    error = failure["error"]
    st.error(error["message"])
    stats_table = build_selection_stats_table(failure.get("selection_stats"))
    if stats_table is not None:
        with st.expander("Selection stats", expanded=True):
            st.table(stats_table)
    # details = error.get("details") or {}
    # if details.get("bag_requirements"):
    #     st.write(
    #         "Bag requirements:",
    #         {
    #             group: {
    #                 "requested": requested,
    #                 "available": details.get("bag_availability", {}).get(group, 0),
    #             }
    #             for group, requested in details["bag_requirements"].items()
    #         },
    #     )


st.set_page_config(page_title="RSA Picker Automation", layout="wide")
st.title("Mystery Run + Pick, Listing, and Order Lists")
with st.expander("Help"):
    st.markdown(
        """
**Instructions**

1. Upload a **.csv** file with at least these columns: `Tags`, `Cost Per Item`, `Variant Price`, `Variant Compare At Price`, `Variant Sku`, `Variant Inventory Qty`, `Title`, `Type`.
2. Fill out the input parameters.
3. Generate the run, click **Edit selected items**, and adjust the selection. You can replace a SKU, change its quantity, delete a row, or add a row before export; product details are refreshed from the uploaded CSV.
4. Click `Confirm and generate lists` and the lists will appear in Google Drive under `RSA Retail/_mystery/_mystery automation/ Job ID`.

**If it's not working**

If you get an error when confirming and generating lists, it may still have gone through and just timed out, so check before trying again.

If generation more than a few seconds, it probably wont find a run matching the criteria. 

1. Wait for the error message and see what went wrong.
2. If you happen to refresh or the app stops responding just and refresh it will work again.
2. Adjust the parameters so they better fit the stock available.

If it fully breaks or you get unexpected errors, send me a message `kreissjason@gmail.com`.
"""
    )

with st.sidebar:
    st.header("Inputs")
    uploaded_csv = st.file_uploader("FILE", type=["csv"], help="Upload the CSV with stock.")
    allow_duplicates = st.toggle(
        "Allow duplicate SKUs",
        value=False,
        help="Allow the same SKU to be selected more than once, capped by Variant Inventory Qty.",
    )
    selected_leagues = None
    team_duplicates_limit = float(TEAM_DUPLICATES_LIMIT)

    limit_team_duplicates = st.toggle(
        "Limit team duplicates",
        value=bool(LIMIT_TEAM_DUPLICATES),
        help="Limit how many selected items can belong to the same team.",
    )
    if limit_team_duplicates:
        team_duplicates_limit = st.slider(
            "Team duplicate limit",
            min_value=0,
            max_value=100,
            value=int(round(float(TEAM_DUPLICATES_LIMIT) * 100)),
            step=1,
            format="%d%%",
            help="Max percent of items one team can have in the final list, only current teams",
        )
        selected_leagues = st.multiselect(
            "Leagues",
            options=ALL_LEAGUES,
            default=None,
            help="Only these leagues are used for team duplicate limits and team counts.",
        )
    email_mode = st.radio(
        "Send lists to email",
        options=["No email", "One email for all lists", "Separate email for each list"],
        help="No emails will be sent unless ticked and input box filled in. If 'Separate email for each list' is chosen, only the filled out inputs will be sent.",
    )
    shared_email = ""
    pick_email = ""
    listing_email = ""
    invoice_email = ""
    if email_mode == "One email for all lists":
        shared_email = st.text_input(
            "Email",
        )
    elif email_mode == "Separate email for each list":
        pick_email = st.text_input("Pick List Email")
        listing_email = st.text_input("Listing List Email")
        invoice_email = st.text_input("Order List Email")
    desired_avg_cost = st.number_input(
        "Average Cost of Item",
        min_value=0.0,
        value=float(DESIRED_AVG_COST_PER_ITEM),
        step=1.0,
        help="Target average cost per selected item. (REQUIRED)",
    )
    num_items = st.number_input(
        "Number of Items",
        min_value=1,
        value=int(NUM_ITEMS),
        step=1,
        help="How many items the generated list should contain on average. (REQUIRED)",
    )
    gold_bag_enabled = st.toggle(
        "Require GOLD BAG items",
        value=False,
        help="Prioritize at least this many items carrying the exact GOLD BAG tag.",
    )
    gold_bag_minimum = 0
    if gold_bag_enabled:
        gold_bag_minimum = st.number_input(
            "Minimum GOLD BAG items",
            min_value=1,
            value=1,
            step=1,
        )
    green_bag_enabled = st.toggle(
        "Require GREEN BAG items",
        value=False,
        help="Prioritize at least this many items carrying the exact GREEN BAG tag.",
    )
    green_bag_minimum = 0
    if green_bag_enabled:
        green_bag_minimum = st.number_input(
            "Minimum GREEN BAG items",
            min_value=1,
            value=1,
            step=1,
        )
    include_tags_raw = st.text_input(
        "Include Tags (comma separated)",
        value=", ".join([x for x in INCLUDE_TAGS if x]),
        help="Only items containing at least one of these tags will be included, case sensitive. If left blank ALL are included (DEFAULT all)",
    )
    exclude_tags_raw = st.text_input(
        "Exclude Tags (comma separated)",
        value=", ".join([x for x in EXCLUDE_TAGS if x]),
        help="Only items containing at least one of these tags will be excluded, case sensitive. If left blank NONE are excluded (DEFAULT none)",
    )
    include_types_raw = st.text_input(
        "Include Types (comma separated)",
        value=", ".join([x for x in INCLUDE_TYPES if x]),
        help="Only items containing at least one of these types will be included, case sensitive. If left blank ALL are included (DEFAULT all)",
    )
    exclude_types_raw = st.text_input(
        "Exclude Types (comma separated)",
        value=", ".join([x for x in EXCLUDE_TYPES if x]),
        help="Only items containing at least one of these types will be excluded, case sensitive. If left blank NONE are excluded (DEFAULT none)",
    )
    minimum_cost = st.number_input(
        "Minimum Cost",
        value=float(MINIMUM_COST),
        step=1.0,
        help="Lowest allowed cost for an individual item. (DEFAULT 0)",
    )
    maximum_cost = st.number_input(
        "Maximum Cost",
        value=float(MAXIMUM_COST),
        step=1.0,
        help="Highest allowed cost for an individual item. (DEFAULT Infinity)",
    )
    count_variance_percent = st.slider(
        "Count Variance",
        min_value=0,
        max_value=100,
        value=int(round(float(COUNT_VARIANCE) * 100)),
        step=5,
        format="%d%%",
        help="How far the final number of items can deviate from the target average. (DEFAULT 0%)",
    )
    avg_tolerance_percent = st.slider(
        "Average Tolerance",
        min_value=0,
        max_value=100,
        value=int(round(float(AVG_TOLERANCE) * 100)),
        step=5,
        format="%d%%",
        help="How far the final average cost can deviate from desired average cost. (DEFAULT 10%)",
    )
    cost_variance = st.slider(
        "Cost Variance",
        min_value=0,
        max_value=300,
        value=int(round(float(COST_VARIANCE) * 100)),
        step=10,
        format="%d%%",
        help="Range of costs able to be selected from. For example, if average cost is 100 and cost variance is 50%, items in the range of \$50 and \$150 can be chosen, unless overridden by min/max cost. (DEFAULT 150%)",
    )
    attempts = st.number_input(
        "Attempts (only change if multiple failures)",
        min_value=1,
        value=int(ATTEMPTS),
        step=5,
        help="Maximum number of generation attempts before giving up. Only change if it keeps failing. (DEFAULT 1)",
    )
    count_variance = count_variance_percent / 100.0
    avg_tolerance = avg_tolerance_percent / 100.0
    cost_variance = cost_variance / 100.0

include_tags = [x.strip() for x in include_tags_raw.split(",") if x.strip()]
exclude_tags = [x.strip() for x in exclude_tags_raw.split(",") if x.strip()]
include_types = [x.strip() for x in include_types_raw.split(",") if x.strip()]
exclude_types = [x.strip() for x in exclude_types_raw.split(",") if x.strip()]
emails = build_email_payload(email_mode, shared_email, pick_email, listing_email, invoice_email)

if "result" not in st.session_state:
    st.session_state.result = None
if "webhook_sent" not in st.session_state:
    st.session_state.webhook_sent = False
if "generation_log" not in st.session_state:
    st.session_state.generation_log = ""
if "current_job_id" not in st.session_state:
    st.session_state.current_job_id = None
if "generation_failure" not in st.session_state:
    st.session_state.generation_failure = None
if "editor_rows" not in st.session_state:
    st.session_state.editor_rows = None
if "editor_errors" not in st.session_state:
    st.session_state.editor_errors = []
if "editor_warnings" not in st.session_state:
    st.session_state.editor_warnings = []
if "editor_version" not in st.session_state:
    st.session_state.editor_version = 0
if "editing_selection" not in st.session_state:
    st.session_state.editing_selection = False
if "selection_edit_snapshot" not in st.session_state:
    st.session_state.selection_edit_snapshot = None
if "source_catalog" not in st.session_state:
    st.session_state.source_catalog = None
if "review_config" not in st.session_state:
    st.session_state.review_config = None
if "allowed_skus" not in st.session_state:
    st.session_state.allowed_skus = None

col1, col2 = st.columns(2)

with col1:
    if st.button("Generate Run", use_container_width=True):
        if uploaded_csv is None:
            st.warning("Upload a CSV file first.")
            st.stop()
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
                tmp_csv.write(uploaded_csv.getvalue())
                csv_path = tmp_csv.name
            job_id = generate_job_id()
            st.session_state.current_job_id = job_id
            log_event(
                "streamlit_generate_clicked",
                job_id=job_id,
                uploaded_filename=uploaded_csv.name,
                desired_avg_cost_per_item=float(desired_avg_cost),
                num_items=int(num_items),
                include_tags=include_tags,
                exclude_tags=exclude_tags,
                include_types=include_types,
                exclude_types=exclude_types,
                minimum_cost=float(minimum_cost),
                maximum_cost=float(maximum_cost),
                count_variance=float(count_variance),
                avg_tolerance=float(avg_tolerance),
                attempts=int(attempts),
                cost_variance=float(cost_variance),
                allow_duplicates=allow_duplicates,
                limit_team_duplicates=limit_team_duplicates,
                team_duplicates_limit=float(team_duplicates_limit) / 100,
                leagues=selected_leagues,
                gold_bag_minimum=int(gold_bag_minimum),
                green_bag_minimum=int(green_bag_minimum),
                emails=emails,
            )
            result = generate_random_list(
                filename=csv_path,
                job_id=job_id,
                desired_avg_cost_per_item=float(desired_avg_cost),
                num_items=int(num_items),
                include_tags=include_tags,
                exclude_tags=exclude_tags,
                include_types=include_types,
                exclude_types=exclude_types,
                minimum_cost=float(minimum_cost),
                maximum_cost=float(maximum_cost),
                count_variance=float(count_variance),
                avg_tolerance=float(avg_tolerance),
                attempts=int(attempts),
                cost_variance=float(cost_variance),
                allow_duplicates=allow_duplicates,
                limit_team_duplicates=limit_team_duplicates,
                team_duplicates_limit=float(team_duplicates_limit) / 100,
                leagues=selected_leagues,
                gold_bag_minimum=int(gold_bag_minimum),
                green_bag_minimum=int(green_bag_minimum),
                emails=emails,
            )
            st.session_state.generation_log = ""
            st.session_state.webhook_sent = False
            st.session_state.editing_selection = False
            st.session_state.selection_edit_snapshot = None
            if picker_results.is_failure_payload(result):
                st.session_state.result = None
                st.session_state.generation_failure = result
                log_event(
                    "streamlit_generate_failed",
                    level="error",
                    job_id=job_id,
                    reason=result["error"]["code"],
                )
            else:
                review_config = PickerConfig(
                    desired_avg_cost_per_item=float(desired_avg_cost),
                    num_items=int(num_items),
                    minimum_cost=float(minimum_cost),
                    maximum_cost=float(maximum_cost),
                    include_tags=include_tags,
                    exclude_tags=exclude_tags,
                    include_types=include_types,
                    exclude_types=exclude_types,
                    count_variance=float(count_variance),
                    avg_tolerance=float(avg_tolerance),
                    attempts=int(attempts),
                    cost_variance=float(cost_variance),
                    allow_duplicates=allow_duplicates,
                    limit_team_duplicates=limit_team_duplicates,
                    team_duplicates_limit=float(team_duplicates_limit) / 100,
                    leagues=selected_leagues,
                    gold_bag_minimum=int(gold_bag_minimum),
                    green_bag_minimum=int(green_bag_minimum),
                )
                source_df = csvhelper.load_csv(csv_path)
                source_catalog = review.build_catalog(source_df)
                filtered_df = filters.filter_df(source_df.copy(), review_config)
                initial_editor_rows = review.editor_rows_from_items(result["items"])
                initial_resolution = review.resolve_editor_rows(initial_editor_rows, source_catalog)

                st.session_state.result = result
                st.session_state.generation_failure = None
                st.session_state.source_catalog = source_catalog
                st.session_state.review_config = review_config
                st.session_state.allowed_skus = {
                    review.normalize_sku(sku) for sku in filtered_df["Variant Sku"]
                }
                st.session_state.editor_rows = initial_resolution.display_df
                st.session_state.editor_errors = initial_resolution.errors
                st.session_state.editor_warnings = review.review_warnings(
                    initial_resolution.selected_df,
                    review_config,
                    st.session_state.allowed_skus,
                )
                st.session_state.editor_version += 1
                log_event("streamlit_generate_succeeded", job_id=job_id)
                st.success("Run generated.")
        except Exception as exc:
            log_event(
                "streamlit_generate_exception",
                level="error",
                job_id=st.session_state.current_job_id,
                error=str(exc),
            )
            st.session_state.generation_log = f"Generation failed: {exc}"
            st.session_state.generation_failure = picker_results.build_failure_payload(
                job_id=st.session_state.current_job_id,
                code="unexpected_exception",
                message=f"Generation failed: {exc}",
                details={"error": str(exc)},
            )
            st.session_state.result = None

with col2:
    if st.session_state.result:
        export_blocked = bool(st.session_state.editor_errors) or st.session_state.editing_selection
        if st.button(
            "Confirm and generate lists",
            use_container_width=True,
            disabled=export_blocked or st.session_state.webhook_sent,
        ):
            job_id = st.session_state.result["job_id"]
            confirm_emails = build_email_payload(
                email_mode,
                shared_email,
                pick_email,
                listing_email,
                invoice_email,
            )
            st.session_state.result["emails"] = confirm_emails
            st.session_state.result.pop("order_export", None)
            invoice_details = st.session_state.result.setdefault("invoice_details", {})
            invoice_details.update(
                {
                    "customer_name": "MYSTERY",
                    "store": "manual orders",
                    "price_source": "Variant Price",
                }
            )
            log_event("streamlit_confirm_clicked", job_id=job_id)
            try:
                invoice_id = ensure_invoice_id(st.session_state.result)
            except InvoiceCounterError as exc:
                log_event(
                    "streamlit_invoice_reservation_failed",
                    level="error",
                    job_id=job_id,
                    error=str(exc),
                )
                st.error("Could not reserve an invoice number. Nothing was sent to the webhook.")
            else:
                log_event(
                    "streamlit_confirm_emails_added",
                    job_id=job_id,
                    email_mode=email_mode,
                    emails=confirm_emails,
                    invoice_id=invoice_id,
                )
                try:
                    webhook_result = send_to_webhook(st.session_state.result)  # DELETE WEBHOOK!!!!!!
                    if webhook_result["ok"]:
                        log_event(
                            "streamlit_confirm_succeeded",
                            job_id=job_id,
                            invoice_id=invoice_id,
                        )
                        st.session_state.webhook_sent = True
                        st.session_state.editing_selection = False
                        st.success(
                            f"Lists Generated\n\n"
                            
                            "Lists can be found in google drive under: "
                            f"'RSA Retail/_mystery/_mystery automation/{st.session_state.result['job_id']}'"

                            f"Invoice number: {invoice_id}\n\n"
                        )

                    else:
                        log_event(
                            "streamlit_confirm_failed",
                            level="error",
                            job_id=job_id,
                            invoice_id=invoice_id,
                            status_code=webhook_result["status_code"],
                            error=webhook_result["error"],
                            response_text=webhook_result["response_text"],
                        )
                        st.error(webhook_result["message"] + "\n\nCheck the drive for folder " + st.session_state.result["job_id"])
                except Exception as exc:
                    log_event(
                        "streamlit_confirm_exception",
                        level="error",
                        job_id=job_id,
                        invoice_id=invoice_id,
                        error=str(exc),
                    )
                    st.error(f"Webhook failed: {exc}")

result = st.session_state.result
if st.session_state.generation_failure is not None:
    render_generation_failure(st.session_state.generation_failure)

if result:
    if st.session_state.webhook_sent:
        # st.info("Confirmed")
        pass
    else:
        st.warning(f"Review the items below, then click 'Confirm and generate lists' if acceptable. \n\n")
    st.subheader("Summary")
    if st.session_state.generation_log:
        st.text(st.session_state.generation_log)
    summary = dict(result["summary"])
    summary.pop("skus", None)
    summary_table = pd.DataFrame(
        [
            {
                "Job ID" : f"{result['job_id']}",
                "Item Count": f"{summary['item_count']}",
                "Average Cost": f"${summary['avg_cost']:.2f}",
                "Total Cost": f"${summary['total_cost']:.2f}",
                "Average Price": f"${summary['avg_price']:.2f}",
                "Average Compare Price": f"${summary['avg_compare_price']:.2f}",
                "GOLD BAG": summary.get("bag_counts", {}).get("GOLD BAG", 0),
                "GREEN BAG": summary.get("bag_counts", {}).get("GREEN BAG", 0),
                "No Bag Tag": summary.get("bag_counts", {}).get("UNTAGGED", 0),
            }
        ]
    )
    st.table(summary_table)
    editor_seed = st.session_state.editor_rows
    selection_column_config = {
        "sku": st.column_config.TextColumn("SKU", required=True),
        "qty": st.column_config.NumberColumn("Quantity", min_value=1, step=1, required=True),
        "cost": st.column_config.NumberColumn("Cost", format="$%.2f"),
        "price": st.column_config.NumberColumn("Retail Price", format="$%.2f"),
        "compare_price": st.column_config.NumberColumn("Compare-at Price", format="$%.2f"),
        "title": st.column_config.TextColumn("Title", width="large"),
        "tags": st.column_config.TextColumn("Tags", width="large"),
        "inventory": st.column_config.NumberColumn("CSV Inventory"),
        "bag_group": st.column_config.TextColumn("Bag Group"),
    }
    title_col, edit_col = st.columns([5, 1])
    with title_col:
        st.subheader("Selected Items")
    with edit_col:
        if not st.session_state.webhook_sent and not st.session_state.editing_selection:
            if st.button("Edit selected items", use_container_width=True):
                st.session_state.selection_edit_snapshot = {
                    "result": copy.deepcopy(st.session_state.result),
                    "editor_rows": st.session_state.editor_rows.copy(deep=True),
                    "editor_errors": list(st.session_state.editor_errors),
                    "editor_warnings": list(st.session_state.editor_warnings),
                }
                st.session_state.editing_selection = True
                st.session_state.editor_version += 1
                st.rerun()

    if st.session_state.editing_selection:
        with st.expander("Help"):
            st.markdown(
            """To **add** a new item scroll to the bottom of the list and click on the blank row.  
             To **delete** an item click the select box beside the sku and press backspace/delete or the trash can in the top right.\n\n"""
             """To prevent mistakes the list will not update unless all items are valid. If its a bad sku or there is limited quantity you will have to delete the row before you save the changes or cancel.  
             Changes will NOT be saved if you cancel or refresh you must press 'Done editing'""")

        edited_rows = st.data_editor(
            editor_seed,
            key=f"selection_editor_{st.session_state.editor_version}",
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            disabled=["cost", "price", "compare_price", "title", "tags", "inventory", "bag_group"],
            column_config=selection_column_config,
        )

        if review.editable_signature(edited_rows) != review.editable_signature(editor_seed):
            resolution = review.resolve_editor_rows(edited_rows, st.session_state.source_catalog)
            st.session_state.editor_rows = resolution.display_df
            st.session_state.editor_errors = resolution.errors
            st.session_state.editor_warnings = []
            if not resolution.errors:
                previous_result = st.session_state.result
                st.session_state.result = picker_results.build_result_payload(
                    resolution.selected_df,
                    job_id=previous_result["job_id"],
                    emails=previous_result["emails"],
                    leagues=st.session_state.review_config.leagues,
                    bag_requirements=previous_result["bag_requirements"],
                )
                st.session_state.editor_warnings = review.review_warnings(
                    resolution.selected_df,
                    st.session_state.review_config,
                    st.session_state.allowed_skus,
                )
            st.session_state.webhook_sent = False
            st.session_state.editor_version += 1
            log_event(
                "streamlit_selection_edited",
                job_id=st.session_state.result["job_id"],
                errors=st.session_state.editor_errors,
                warnings=st.session_state.editor_warnings,
            )
            st.rerun()
    else:
        st.dataframe(
            editor_seed,
            use_container_width=True,
            hide_index=True,
            column_config=selection_column_config,
        )

    for error in st.session_state.editor_errors:
        st.error(error)
    for warning in st.session_state.editor_warnings:
        st.warning(warning)
    if st.session_state.editing_selection:
        done_col, cancel_col = st.columns(2)
        with done_col:
            done_editing = st.button(
                "Done editing",
                disabled=bool(st.session_state.editor_errors),
                use_container_width=True,
            )
        with cancel_col:
            cancel_editing = st.button("Cancel", use_container_width=True)

        if cancel_editing:
            snapshot = st.session_state.selection_edit_snapshot
            if snapshot is not None:
                st.session_state.result = copy.deepcopy(snapshot["result"])
                st.session_state.editor_rows = snapshot["editor_rows"].copy(deep=True)
                st.session_state.editor_errors = list(snapshot["editor_errors"])
                st.session_state.editor_warnings = list(snapshot["editor_warnings"])
            st.session_state.selection_edit_snapshot = None
            st.session_state.editing_selection = False
            st.session_state.editor_version += 1
            log_event(
                "streamlit_selection_edit_cancelled",
                job_id=st.session_state.result["job_id"],
            )
            st.rerun()
        if done_editing:
            st.session_state.selection_edit_snapshot = None
            st.session_state.editing_selection = False
            st.session_state.editor_version += 1
            st.rerun()
    if limit_team_duplicates:
        team_counts_table = build_team_counts_table(summary.get("team_counts"))
        if team_counts_table is not None:
            st.subheader("Team Counts")
            st.dataframe(team_counts_table, use_container_width=True, hide_index=True)
