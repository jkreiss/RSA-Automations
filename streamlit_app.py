import importlib.util
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


def shopify_gql(shop: str, token: str, api_version: str, query: str, variables=None):
    url = f"https://{shop}/admin/api/{api_version}/graphql.json"
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token},
    )
    with request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_primary_location_id(shop: str, token: str, api_version: str):
    query = "query { location { id name } }"
    data = shopify_gql(shop, token, api_version, query)
    return data["data"]["location"]["id"]


def get_inventory_item_id_by_sku(shop: str, token: str, api_version: str, sku: str):
    query = """
    query($q: String!) {
      inventoryItems(first: 1, query: $q) { nodes { id sku tracked } }
    }
    """
    data = shopify_gql(shop, token, api_version, query, {"q": f"sku:{sku}"})
    nodes = data["data"]["inventoryItems"]["nodes"]
    return nodes[0]["id"] if nodes else None


def decrement_shopify_inventory(
    items,
    shop: str,
    token: str,
    api_version: str,
    location_id: str | None,
    reason: str,
    quantity_name: str,
):
    resolved_location_id = location_id or get_primary_location_id(shop, token, api_version)
    changes = []
    missing_skus = []

    for item in items:
        sku = str(item["sku"])
        qty = int(item.get("qty", 1))
        inventory_item_id = get_inventory_item_id_by_sku(shop, token, api_version, sku)
        if not inventory_item_id:
            missing_skus.append(sku)
            continue
        changes.append(
            {
                "inventoryItemId": inventory_item_id,
                "locationId": resolved_location_id,
                "delta": -qty,
            }
        )

    if not changes:
        return {"ok": False, "missing_skus": missing_skus, "errors": ["No inventory changes were prepared."]}

    mutation = """
    mutation Adjust($input: InventoryAdjustQuantitiesInput!, $idempotencyKey: String!) {
      inventoryAdjustQuantities(input: $input) @idempotent(key: $idempotencyKey) {
        userErrors { field message }
      }
    }
    """

    variables = {
        "input": {"reason": reason, "name": quantity_name, "changes": changes},
        "idempotencyKey": str(uuid.uuid4()),
    }
    response = shopify_gql(shop, token, api_version, mutation, variables)
    user_errors = response.get("data", {}).get("inventoryAdjustQuantities", {}).get("userErrors", [])
    return {
        "ok": len(user_errors) == 0,
        "missing_skus": missing_skus,
        "user_errors": user_errors,
        "changes_count": len(changes),
        "location_id": resolved_location_id,
    }


def normalize_csv_candidates():
    candidates = sorted(str(p) for p in pathlib.Path(".").glob("*.csv"))
    return candidates if candidates else [""]


st.set_page_config(page_title="RSA Picker Automation", layout="wide")
st.title("RSA Picker Automation")

default_script = "picker-automation.py"
module = load_picker_module(default_script)

with st.sidebar:
    st.header("Inputs")
    uploaded_csv = st.file_uploader("FILE", type=["csv"])
    desired_avg_cost = st.number_input(
        "DESIRED_AVG_COST_PER_ITEM", min_value=0.0, value=float(module.DESIRED_AVG_COST_PER_ITEM), step=1.0
    )
    num_items = st.number_input("NUM_ITEMS", min_value=1, value=int(module.NUM_ITEMS), step=1)
    include_tags_raw = st.text_input("INCLUDE_TAGS (comma-separated)", value=", ".join([x for x in module.INCLUDE_TAGS if x]))
    exclude_tags_raw = st.text_input("EXCLUDE_TAGS (comma-separated)", value=", ".join([x for x in module.EXCLUDE_TAGS if x]))
    include_types_raw = st.text_input("INCLUDE_TYPES (comma-separated)", value=", ".join([x for x in module.INCLUDE_TYPES if x]))
    exclude_types_raw = st.text_input("EXCLUDE_TYPES (comma-separated)", value=", ".join([x for x in module.EXCLUDE_TYPES if x]))
    minimum_cost = st.number_input("MINIMUM_COST", value=float(module.MINIMUM_COST), step=1.0)
    maximum_cost = st.number_input("MAXIMUM_COST", value=float(module.MAXIMUM_COST), step=1.0)
    count_variance = st.number_input("COUNT_VARIANCE", min_value=0.0, value=float(module.COUNT_VARIANCE), step=0.01)
    avg_tolerance = st.number_input("AVG_TOLERANCE", min_value=0.0, value=float(module.AVG_TOLERANCE), step=0.01)
    cost_variance = st.number_input("COST_VARIANCE", min_value=0.0, value=float(module.COST_VARIANCE), step=0.1)
    attempts = st.number_input("ATTEMPTS", min_value=1, value=int(module.ATTEMPTS), step=10)

include_tags = [x.strip() for x in include_tags_raw.split(",") if x.strip()]
exclude_tags = [x.strip() for x in exclude_tags_raw.split(",") if x.strip()]
include_types = [x.strip() for x in include_types_raw.split(",") if x.strip()]
exclude_types = [x.strip() for x in exclude_types_raw.split(",") if x.strip()]

if "result" not in st.session_state:
    st.session_state.result = None
if "webhook_sent" not in st.session_state:
    st.session_state.webhook_sent = False

col1, col2 = st.columns(2)

with col1:
    if st.button("Generate Lists", use_container_width=True):
        if uploaded_csv is None:
            st.warning("Upload a CSV file first.")
            st.stop()
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
                tmp_csv.write(uploaded_csv.getvalue())
                csv_path = tmp_csv.name
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
            st.session_state.result = result
            st.session_state.webhook_sent = False
            if result:
                st.success("List generated.")
            else:
                st.warning("No valid list found with the current settings.")
        except Exception as exc:
            st.error(f"Generation failed: {exc}")

with col2:
    if st.session_state.result:
        if st.button("Confirm and Send to Webhook", use_container_width=True):
            try:
                ok = module.send_to_webhook(st.session_state.result)
                if ok:
                    st.session_state.webhook_sent = True
                    st.success("Webhook sent.")
                else:
                    st.error("Webhook call failed.")
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
        st.info("Confirmed and sent to webhook.")
    else:
        st.warning("Review the selection below, then click 'Confirm and Send to Webhook'.")
    st.subheader("Summary")
    st.json(result["summary"])
    st.subheader("Selected Items")
    st.dataframe(pd.DataFrame(result["items"]), use_container_width=True)
