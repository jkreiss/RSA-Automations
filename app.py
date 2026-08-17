import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from picker import results as picker_results
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
    MAXIMUM_COST,
    MINIMUM_COST,
    NUM_ITEMS,
    generate_random_list,
)
from picker.webhook import send_to_webhook


DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
DEMO_CSV_PATH = Path(__file__).resolve().parent / "democsv.csv"


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
    return "" if value is None else f"${value:.2f}"


def build_selection_stats_table(stats):
    if not stats:
        return None

    rows = [
        ("Unique Player Titles", stats["unique_players"]),
        ("Unique SKUs", stats["unique_skus"]),
        ("Number of items that can be chosen from", stats["unique_capacity"]),
        ("Average cost with parameters", format_money(stats["best_possible_avg"])),
        ("Allowed Item Range", f"{stats['min_items']} - {stats['max_items']}"),
        ("Allowed Average Range", f"\${stats['low_avg']:.2f} - \${stats['high_avg']:.2f}"),
        ("Pool Average Cost", format_money(stats["pool_avg"])),
        ("Pool Min/Max Costs", f"\${stats['pool_min_cost']:.2f} - \${stats['pool_max_cost']:.2f}"),
        ("Enough Items", "Yes" if stats["count_possible"] else "No"),
        ("Average Possible For Requested Count", "Yes" if stats["avg_possible_for_requested_count"] else "No"),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def render_generation_failure(failure):
    error = failure["error"]
    st.error(error["message"])
    stats_table = build_selection_stats_table(failure.get("selection_stats"))
    if stats_table is not None:
        with st.expander("Selection stats", expanded=True):
            st.table(stats_table)


st.set_page_config(page_title="RSA Picker Automation", layout="wide")
st.title("Mystery Run + Pick, Listing, and Invoice Lists")
if DEMO_MODE:
    st.info(
        "Demo mode just click generate no need to upload, no back end capabilities"
    )
with st.expander("Help"):
    st.markdown(
        """
**Instructions**

1. Upload a **.csv** file with at least these columns: `Tags`, `Cost Per Item`, `Variant Price`, `Variant Compare At Price`, `Variant Sku`, `Title`.
2. Fill out the input parameters.
3. Generate the run and review the selection.
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
    csv_source = uploaded_csv
    csv_filename = uploaded_csv.name if uploaded_csv is not None else None
    if csv_source is None and DEMO_MODE and DEMO_CSV_PATH.exists():
        csv_source = DEMO_CSV_PATH
        csv_filename = DEMO_CSV_PATH.name
        st.caption("Using bundled demo file: democsv.csv")
    allow_duplicates = st.toggle(
        "Allow duplicate SKUs",
        value=False,
        help="Allow the same SKU to be selected more than once, capped by Variant Inventory Qty.",
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
        invoice_email = st.text_input("Invoice List Email")
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
        help="Range of costs able to be selected from. For example, if average cost is 100 and cost variance is 50%, items in the range of $50 and $150 can be chosen, unless overridden by min/max cost. (DEFAULT 150%)",
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

col1, col2 = st.columns(2)

with col1:
    if st.button("Generate Run", use_container_width=True):
        if csv_source is None:
            st.warning("Upload a CSV file first.")
            st.stop()
        try:
            if hasattr(csv_source, "getvalue"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
                    tmp_csv.write(csv_source.getvalue())
                    csv_path = tmp_csv.name
            else:
                csv_path = str(csv_source)
            job_id = generate_job_id()
            st.session_state.current_job_id = job_id
            log_event(
                "streamlit_generate_clicked",
                job_id=job_id,
                uploaded_filename=csv_filename,
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
                emails=emails,
            )
            st.session_state.generation_log = ""
            st.session_state.webhook_sent = False
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
                st.session_state.result = result
                st.session_state.generation_failure = None
                log_event("streamlit_generate_succeeded", job_id=job_id)
                st.success('Run generated. \n\nReview the lists below and click "Confirm and generate lists" if they are acceptable')
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
        if st.button("Confirm and generate lists", use_container_width=True):
            job_id = st.session_state.result["job_id"]
            confirm_emails = build_email_payload(
                email_mode,
                shared_email,
                pick_email,
                listing_email,
                invoice_email,
            )
            st.session_state.result["emails"] = confirm_emails
            log_event("streamlit_confirm_clicked", job_id=job_id)
            log_event(
                "streamlit_confirm_emails_added",
                job_id=job_id,
                email_mode=email_mode,
                emails=confirm_emails,
            )
            try:
                if DEMO_MODE:
                    webhook_result = {
                        "ok": True,
                        "job_id": job_id,
                        "status_code": None,
                        "message": "Demo mode: lists generated locally only.",
                        "response_text": "",
                    }

                else:
                    webhook_result = send_to_webhook(st.session_state.result)
                if webhook_result["ok"]:
                    log_event("streamlit_confirm_succeeded", job_id=job_id)
                    st.session_state.webhook_sent = True
                    if DEMO_MODE:
                        st.error("List generation failed. \n\nIs your device still connected to the Tailnet?")
                    else:
                        st.success("Lists Generated \n\n"
                                   "Lists can be found in google drive under: 'RSA Retail/_mystery/_mystery automation/" + st.session_state.result["job_id"] + "'")

                else:
                    log_event(
                        "streamlit_confirm_failed",
                        level="error",
                        job_id=job_id,
                        status_code=webhook_result["status_code"],
                        error=webhook_result["error"],
                        response_text=webhook_result["response_text"],
                    )
                    st.error(webhook_result["message"] + "\n\nCheck the drive for folder " + st.session_state.result["job_id"])
            except Exception as exc:
                log_event("streamlit_confirm_exception", level="error", job_id=job_id, error=str(exc))
                st.error(f"Webhook failed: {exc}")

result = st.session_state.result
if st.session_state.generation_failure is not None:
    render_generation_failure(st.session_state.generation_failure)

if result:
    if st.session_state.webhook_sent:
        # st.info("Confirmed")
        pass
    else:
        pass
        # st.warning(f"Review the items below, then click 'Confirm and generate lists' if acceptable. \n\n")
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
            }
        ]
    )
    st.table(summary_table)
    st.subheader("Selected Items")
    st.dataframe(pd.DataFrame(result["items"]), use_container_width=True)
