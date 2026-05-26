import contextlib
import importlib.util
import io
import json
import pathlib
import tempfile
import uuid
from urllib import request

import pandas as pd
import streamlit as st


def load_picker_module(script_path: str):
    spec = importlib.util.spec_from_file_location("picker_automation_module", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def normalize_csv_candidates():
    candidates = sorted(str(p) for p in pathlib.Path(".").glob("*.csv"))
    return candidates if candidates else [""]


st.set_page_config(page_title="RSA Picker Automation", layout="wide")
st.title("Mystery Run + Pick, Listing, and Invoice Lists")
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

default_script = "picker-automation.py"
module = load_picker_module(default_script)

with st.sidebar:
    st.header("Inputs")
    uploaded_csv = st.file_uploader("FILE", type=["csv"], help="Upload the CSV with stock.")
    desired_avg_cost = st.number_input(
        "Average Cost of Item",
        min_value=0.0,
        value=float(module.DESIRED_AVG_COST_PER_ITEM),
        step=1.0,
        help="Target average cost per selected item. (REQUIRED)",
    )
    num_items = st.number_input(
        "Number of Items",
        min_value=1,
        value=int(module.NUM_ITEMS),
        step=1,
        help="How many items the generated list should contain on average. (REQUIRED)",
    )
    include_tags_raw = st.text_input(
        "Include Tags (comma separated)",
        value=", ".join([x for x in module.INCLUDE_TAGS if x]),
        help="Only items containing at least one of these tags will be included. If left blank ALL are included (DEFAULT all)",
    )
    exclude_tags_raw = st.text_input(
        "Exclude Tags (comma separated)",
        value=", ".join([x for x in module.EXCLUDE_TAGS if x]),
        help="Only items containing at least one of these tags will be excluded. If left blank NONE are excluded (DEFAULT none)",
    )
    include_types_raw = st.text_input(
        "Include Types (comma separated)",
        value=", ".join([x for x in module.INCLUDE_TYPES if x]),
        help="Only items containing at least one of these types will be included. If left blank ALL are included (DEFAULT all)",
    )
    exclude_types_raw = st.text_input(
        "Exclude Types (comma separated)",
        value=", ".join([x for x in module.EXCLUDE_TYPES if x]),
        help="Only items containing at least one of these types will be excluded. If left blank NONE are excluded (DEFAULT none)",
    )
    minimum_cost = st.number_input(
        "Minimum Cost",
        value=float(module.MINIMUM_COST),
        step=10.0,
        help="Lowest allowed cost for an individual item. (DEFAULT 0)",
    )
    maximum_cost = st.number_input(
        "Maximum Cost",
        value=float(module.MAXIMUM_COST),
        step=10.0,
        help="Highest allowed cost for an individual item. (DEFAULT Infinity)",
    )
    count_variance_percent = st.slider(
        "Count Variance",
        min_value=0,
        max_value=100,
        value=int(round(float(module.COUNT_VARIANCE) * 100)),
        step=5,
        format="%d%%",
        help="How far the final number of items can deviate from the target average. (DEFAULT 0%)",
    )
    avg_tolerance_percent = st.slider(
        "Average Tolerance",
        min_value=0,
        max_value=100,
        value=int(round(float(module.AVG_TOLERANCE) * 100)),
        step=5,
        format="%d%%",
        help="How far the final average cost can deviate from desired average cost. (DEFAULT 10%)",
    )
    cost_variance = st.slider(
        "Cost Variance",
        min_value=0,
        max_value=300,
        value=int(round(float(module.COST_VARIANCE) * 100)),
        step=10,
        format="%d%%",
        help="Range of costs able to be selected from. For example, if average cost is 100 and cost variance is 50%, items in the range of $50 and $150 can be chosen, unless overridden by min/max cost. (DEFAULT 150%)",
    )
    attempts = st.number_input(
        "Attempts (only change if multiple failures)",
        min_value=1,
        value=int(module.ATTEMPTS),
        step=5,
        help="Maximum number of generation attempts before giving up. Only change if it keeps failing. (DEFAULT 200)",
    )
    count_variance = count_variance_percent / 100.0
    avg_tolerance = avg_tolerance_percent / 100.0
    cost_variance = cost_variance / 100.0

include_tags = [x.strip() for x in include_tags_raw.split(",") if x.strip()]
exclude_tags = [x.strip() for x in exclude_tags_raw.split(",") if x.strip()]
include_types = [x.strip() for x in include_types_raw.split(",") if x.strip()]
exclude_types = [x.strip() for x in exclude_types_raw.split(",") if x.strip()]

if "result" not in st.session_state:
    st.session_state.result = None
if "webhook_sent" not in st.session_state:
    st.session_state.webhook_sent = False
if "generation_log" not in st.session_state:
    st.session_state.generation_log = ""

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
            log_buffer = io.StringIO()
            with contextlib.redirect_stdout(log_buffer):
                result = module.generate_random_list(
                    filename=csv_path,
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
                )
            st.session_state.generation_log = log_buffer.getvalue().strip()
            st.session_state.result = result
            st.session_state.webhook_sent = False
            if result:
                st.success("Run generated.")
            else:
                failure_message = st.session_state.generation_log or "Unexpected failure"
                st.error("No valid list found with the current settings.")
                st.text(failure_message)
        except Exception as exc:
            st.session_state.generation_log = f"Generation failed: {exc}"
            st.error(f"Generation failed: {exc}")

with col2:
    if st.session_state.result:
        if st.button("Confirm and generate lists", use_container_width=True):
            try:
                ok = module.send_to_webhook(st.session_state.result)
                if ok:
                    st.session_state.webhook_sent = True
                    st.success("Lists Generated")
                else:
                    st.error("Something went wrong. \n\nThe lists may have still generated, check the drive for folder " + st.session_state.result["job_id"])
            except Exception as exc:
                st.error(f"Webhook failed: {exc}")

# with col2:
#     if st.button("Decrement Local CSV Inventory", use_container_width=True):
#         if not st.session_state.result:
#             st.warning("Generate a list first.")
#         else:
#             try:
#                 module = load_picker_module(script_path)
#                 module.decrement_inventory_in_csv(csv_path, st.session_state.result["items"])
#                 st.success("CSV inventory decremented.")
#             except Exception as exc:
#                 st.error(f"CSV decrement failed: {exc}")
#
# with col3:
#     webhook_url = st.text_input("Webhook URL (optional)", value="")
#     if st.button("Send Result To Webhook", use_container_width=True):
#         if not st.session_state.result:
#             st.warning("Generate a list first.")
#         elif not webhook_url.strip():
#             st.warning("Enter a webhook URL first.")
#         else:
#             try:
#                 module = load_picker_module(script_path)
#                 ok = module.send_to_webhook(st.session_state.result, webhook_url=webhook_url.strip())
#                 if ok:
#                     st.success("Webhook sent.")
#                 else:
#                     st.error("Webhook call failed.")
#             except Exception as exc:
#                 st.error(f"Webhook failed: {exc}")
#
# with st.expander("Shopify Inventory Decrement"):
#     shop = st.text_input("Shop Domain", value="your-store.myshopify.com")
#     token = st.text_input("Admin API Access Token", value="", type="password")
#     api_version = st.text_input("API Version", value="2026-04")
#     location_id = st.text_input("Location ID (optional; blank uses primary)", value="")
#     reason = st.text_input("Reason", value="correction")
#     quantity_name = st.text_input("Quantity Name", value="available")
#
#     if st.button("Decrement Shopify Inventory"):
#         if not st.session_state.result:
#             st.warning("Generate a list first.")
#         elif not shop.strip() or not token.strip():
#             st.warning("Enter Shop Domain and Admin API token.")
#         else:
#             try:
#                 response = decrement_shopify_inventory(
#                     st.session_state.result["items"],
#                     shop=shop.strip(),
#                     token=token.strip(),
#                     api_version=api_version.strip(),
#                     location_id=location_id.strip() or None,
#                     reason=reason.strip(),
#                     quantity_name=quantity_name.strip(),
#                 )
#                 if response["ok"]:
#                     st.success(
#                         f"Shopify inventory decremented for {response['changes_count']} item(s) at {response['location_id']}."
#                     )
#                 else:
#                     st.error("Shopify decrement completed with errors.")
#                 if response.get("missing_skus"):
#                     st.warning(f"Missing SKUs in Shopify: {', '.join(response['missing_skus'])}")
#                 if response.get("user_errors"):
#                     st.json(response["user_errors"])
#             except Exception as exc:
#                 st.error(f"Shopify decrement failed: {exc}")

result = st.session_state.result
if result:
    if st.session_state.webhook_sent:
        st.info("Confirmed")
    else:
        st.warning(f"Review the items below, then click 'Confirm and generate lists' if acceptable. \n\n"
                   f"Lists can then be found in google drive under: 'RSA Retail/_mystery/_mystery automation/" + result["job_id"] + "'")
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
