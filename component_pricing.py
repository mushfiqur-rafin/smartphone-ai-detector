"""
component_pricing.py
Live smartphone replacement-component pricing for the Smartphone AI Detector.

Priority:
1. Official eBay Browse API when credentials are configured.
2. Existing researched component_value_config.json fallback.

IMPORTANT:
- eBay values are CURRENT ACTIVE ASKING PRICES, not completed/sold prices.
- CTIA does not define component prices.
- Replacement-part value is not whole-phone resale value or recycling value.
"""

from __future__ import annotations

import base64
import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import streamlit as st
except Exception:
    st = None


EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"
EBAY_MARKETPLACE = "EBAY_US"

DEFAULT_FALLBACK_PATH = (
    Path(__file__).resolve().parent / "data" / "component_value_config.json"
)

MODEL_NAMES = {
    "iphone_14": "Apple iPhone 14",
    "iphone_14_pro_max": "Apple iPhone 14 Pro Max",
    "iphone_15_pro": "Apple iPhone 15 Pro",
    "iphone_15_pro_max": "Apple iPhone 15 Pro Max",
    "s24_ultra": "Samsung Galaxy S24 Ultra",
    "s25_ultra": "Samsung Galaxy S25 Ultra",
    "s25_edge": "Samsung Galaxy S25 Edge",
}

MODEL_ALIASES = {
    "iphone 14": "iphone_14",
    "apple iphone 14": "iphone_14",
    "iphone 14 pro max": "iphone_14_pro_max",
    "apple iphone 14 pro max": "iphone_14_pro_max",
    "iphone 15 pro": "iphone_15_pro",
    "apple iphone 15 pro": "iphone_15_pro",
    "iphone 15 pro max": "iphone_15_pro_max",
    "apple iphone 15 pro max": "iphone_15_pro_max",
    "s24 ultra": "s24_ultra",
    "galaxy s24 ultra": "s24_ultra",
    "samsung galaxy s24 ultra": "s24_ultra",
    "s25 ultra": "s25_ultra",
    "galaxy s25 ultra": "s25_ultra",
    "samsung galaxy s25 ultra": "s25_ultra",
    "s25 edge": "s25_edge",
    "galaxy s25 edge": "s25_edge",
    "samsung galaxy s25 edge": "s25_edge",
}

# Component-specific search/matching rules.
# include_any: at least one phrase should occur.
# require_any_groups: at least one term from EACH group must occur.
# exclude: reject misleading/accessory/service listings.
COMPONENT_RULES: Dict[str, Dict[str, Any]] = {
    "Display Assembly": {
        "query": "display screen assembly replacement",
        "include_any": ["display", "screen", "oled", "lcd"],
        "require_any_groups": [["display", "screen", "oled", "lcd"]],
        "exclude": ["protector", "tempered glass", "case", "repair service", "tool", "broken", "for parts"],
    },
    "OLED Display Assembly": {
        "query": "OLED display screen assembly replacement",
        "include_any": ["oled", "display", "screen"],
        "require_any_groups": [["oled", "display", "screen"]],
        "exclude": ["protector", "tempered glass", "case", "repair service", "tool", "broken", "for parts"],
    },
    "Battery": {
        "query": "battery replacement",
        "include_any": ["battery"],
        "require_any_groups": [["battery"]],
        "exclude": ["case", "charger", "charging cable", "power bank", "tool kit", "battery case"],
    },
    "Rear Camera Assembly": {
        "query": "rear main camera module replacement",
        "include_any": ["rear camera", "main camera", "back camera", "camera module"],
        "require_any_groups": [["camera"]],
        "exclude": ["lens protector", "camera glass", "lens glass", "case", "cover", "repair service"],
    },
    "Rear Camera Module": {
        "query": "rear main camera module replacement",
        "include_any": ["rear camera", "main camera", "back camera", "camera module"],
        "require_any_groups": [["camera"]],
        "exclude": ["lens protector", "camera glass", "lens glass", "case", "cover", "repair service"],
    },
    "Front Camera": {
        "query": "front selfie camera module replacement",
        "include_any": ["front camera", "selfie camera", "camera module"],
        "require_any_groups": [["front", "selfie"], ["camera"]],
        "exclude": ["protector", "glass", "case", "repair service"],
    },
    "Front Camera Assembly": {
        "query": "front selfie camera module replacement",
        "include_any": ["front camera", "selfie camera", "camera module"],
        "require_any_groups": [["front", "selfie"], ["camera"]],
        "exclude": ["protector", "glass", "case", "repair service"],
    },
    "Back Glass": {
        "query": "back rear glass replacement",
        "include_any": ["back glass", "rear glass", "battery cover", "back cover"],
        "require_any_groups": [["back", "rear", "battery cover"]],
        "exclude": ["case", "protector", "camera lens", "repair service", "sticker"],
    },
    "Back Cover / Rear Glass": {
        "query": "back rear glass cover replacement",
        "include_any": ["back glass", "rear glass", "back cover", "battery cover"],
        "require_any_groups": [["back", "rear", "battery cover"]],
        "exclude": ["case", "protector", "camera lens", "repair service", "sticker"],
    },
    "Charging Port Assembly": {
        "query": "charging port flex assembly replacement",
        "include_any": ["charging port", "charge port", "dock connector", "usb-c port", "lightning port"],
        "require_any_groups": [["charging", "charge", "dock", "usb", "lightning"]],
        "exclude": ["charger", "cable", "wall adapter", "case", "repair service"],
    },
    "Lightning Connector Assembly": {
        "query": "lightning charging port flex replacement",
        "include_any": ["lightning", "charging port", "dock connector"],
        "require_any_groups": [["lightning", "charging", "dock"]],
        "exclude": ["cable", "charger", "adapter", "repair service"],
    },
    "Wireless Charging / NFC": {
        "query": "wireless charging NFC coil replacement",
        "include_any": ["wireless charging", "nfc", "charging coil"],
        "require_any_groups": [["wireless", "nfc", "coil"]],
        "exclude": ["charger pad", "charging stand", "case", "magsafe charger"],
    },
    "Wireless Charging Antenna": {
        "query": "wireless charging NFC antenna coil replacement",
        "include_any": ["wireless charging", "nfc", "antenna", "coil"],
        "require_any_groups": [["wireless", "nfc", "coil", "antenna"]],
        "exclude": ["charger pad", "stand", "case"],
    },
    "Loudspeaker": {
        "query": "loudspeaker buzzer ringer replacement",
        "include_any": ["loudspeaker", "loud speaker", "buzzer", "ringer speaker"],
        "require_any_groups": [["speaker", "buzzer", "ringer"]],
        "exclude": ["bluetooth speaker", "case", "earpiece", "repair service"],
    },
    "Speaker": {
        "query": "loudspeaker buzzer ringer replacement",
        "include_any": ["loudspeaker", "speaker", "buzzer", "ringer"],
        "require_any_groups": [["speaker", "buzzer", "ringer"]],
        "exclude": ["bluetooth speaker", "case", "earpiece", "repair service"],
    },
    "Loudspeaker with Vibrator": {
        "query": "loudspeaker vibrator assembly replacement",
        "include_any": ["loudspeaker", "speaker", "vibrator", "vibration"],
        "require_any_groups": [["speaker", "loudspeaker"], ["vibrator", "vibration"]],
        "exclude": ["bluetooth speaker", "case", "repair service"],
    },
    "Earpiece Speaker": {
        "query": "earpiece speaker replacement",
        "include_any": ["earpiece", "ear speaker", "receiver speaker"],
        "require_any_groups": [["earpiece", "receiver", "ear speaker"]],
        "exclude": ["loudspeaker", "bluetooth", "case", "repair service"],
    },
    "Taptic Engine": {
        "query": "taptic engine vibration motor replacement",
        "include_any": ["taptic", "vibration motor", "vibrator"],
        "require_any_groups": [["taptic", "vibration", "vibrator"]],
        "exclude": ["case", "repair service"],
    },
    "Vibration Motor": {
        "query": "vibration motor vibrator replacement",
        "include_any": ["vibration motor", "vibrator"],
        "require_any_groups": [["vibration", "vibrator"]],
        "exclude": ["case", "repair service"],
    },
    "Power / Volume Button Assembly": {
        "query": "power volume button flex cable replacement",
        "include_any": ["power button", "volume button", "button flex", "flex cable"],
        "require_any_groups": [["power", "volume", "button"], ["flex", "cable", "button"]],
        "exclude": ["case", "external button", "repair service"],
    },
    "Frame / Midframe": {
        "query": "frame midframe housing replacement",
        "include_any": ["midframe", "frame", "housing"],
        "require_any_groups": [["midframe", "frame", "housing"]],
        "exclude": ["case", "bumper case", "repair service"],
    },
    "Main Logic Board": {
        "query": "main logic board motherboard replacement",
        "include_any": ["logic board", "motherboard", "main board"],
        "require_any_groups": [["logic board", "motherboard", "main board"]],
        "exclude": ["repair service", "for parts", "locked", "icloud", "bad imei"],
    },
    "Charging / Sub Board (Daughterboard)": {
        "query": "charging sub board daughterboard replacement",
        "include_any": ["daughterboard", "daughter board", "sub board", "charging board"],
        "require_any_groups": [["daughter", "sub board", "charging board"]],
        "exclude": ["charger", "cable", "repair service"],
    },
    "Daughterboard": {
        "query": "charging sub board daughterboard replacement",
        "include_any": ["daughterboard", "daughter board", "sub board", "charging board"],
        "require_any_groups": [["daughter", "sub board", "charging board"]],
        "exclude": ["charger", "cable", "repair service"],
    },
    "Microphone": {
        "query": "microphone mic flex replacement",
        "include_any": ["microphone", "mic flex"],
        "require_any_groups": [["microphone", "mic"]],
        "exclude": ["external microphone", "wireless mic", "repair service"],
    },
    "Adhesive / Gasket": {
        "query": "adhesive gasket seal replacement",
        "include_any": ["adhesive", "gasket", "seal"],
        "require_any_groups": [["adhesive", "gasket", "seal"]],
        "exclude": ["bulk roll", "tool", "repair service"],
    },
}

GENERIC_EXCLUDE = [
    "phone case", "protective case", "screen protector", "tempered glass",
    "repair service", "installation service", "tool kit", "tools only",
    "manual", "box only", "dummy phone", "for parts only",
]

OEM_POSITIVE = [
    "oem", "original", "genuine", "service pack", "servicepack",
    "pulled", "pull", "take off",
]
AFTERMARKET_POSITIVE = [
    "aftermarket", "replacement", "compatible", "incell", "in-cell",
    "generic", "third party", "3rd party",
]

_token_cache = {"token": None, "expires_at": 0.0}


def _secret(name: str) -> Optional[str]:
    if st is not None:
        try:
            value = st.secrets.get(name)
            if value:
                return str(value)
        except Exception:
            pass
    return os.getenv(name)


def ebay_configured() -> bool:
    return bool(_secret("EBAY_CLIENT_ID") and _secret("EBAY_CLIENT_SECRET"))


def _access_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    cid = _secret("EBAY_CLIENT_ID")
    secret = _secret("EBAY_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("eBay credentials are not configured.")

    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = requests.post(
        EBAY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": EBAY_SCOPE},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 7200))
    return _token_cache["token"]


def normalize_model_key(model: str) -> str:
    raw = str(model or "").strip()
    if raw in MODEL_NAMES:
        return raw
    cleaned = raw.lower().replace("_", " ").replace("-", " ")
    cleaned = " ".join(cleaned.split())
    return MODEL_ALIASES.get(cleaned, raw.lower().replace(" ", "_"))


def model_display_name(model: str) -> str:
    key = normalize_model_key(model)
    return MODEL_NAMES.get(key, str(model))


def _normalize_component(name: str) -> str:
    s = re.sub(r"\s+", " ", str(name or "").strip())
    aliases = {
        "display": "Display Assembly",
        "screen": "Display Assembly",
        "rear camera": "Rear Camera Assembly",
        "rear camera module": "Rear Camera Module",
        "front camera module": "Front Camera",
        "charging port": "Charging Port Assembly",
        "wireless charging coil": "Wireless Charging / NFC",
        "back cover": "Back Cover / Rear Glass",
        "rear glass": "Back Cover / Rear Glass",
        "speaker": "Speaker",
        "sub board": "Charging / Sub Board (Daughterboard)",
        "charging board": "Charging / Sub Board (Daughterboard)",
    }
    return aliases.get(s.lower(), s)


def _rule(component: str) -> Dict[str, Any]:
    component = _normalize_component(component)
    if component in COMPONENT_RULES:
        return COMPONENT_RULES[component]
    words = [w for w in re.findall(r"[a-z0-9]+", component.lower()) if len(w) > 2]
    return {
        "query": f"{component} replacement",
        "include_any": words,
        "require_any_groups": [words] if words else [],
        "exclude": ["case", "protector", "repair service"],
    }


def _title_matches(title: str, model: str, component: str) -> bool:
    t = title.lower()
    if any(x in t for x in GENERIC_EXCLUDE):
        return False

    model_name = model_display_name(model).lower()
    # Require distinctive model tokens, not generic Apple/Samsung/Galaxy words.
    tokens = [
        x for x in re.findall(r"[a-z0-9]+", model_name)
        if x not in {"apple", "samsung", "galaxy"}
    ]
    if not all(x in t for x in tokens):
        return False

    rule = _rule(component)
    if any(x.lower() in t for x in rule.get("exclude", [])):
        return False

    includes = [x.lower() for x in rule.get("include_any", [])]
    if includes and not any(x in t for x in includes):
        return False

    for group in rule.get("require_any_groups", []):
        if group and not any(x.lower() in t for x in group):
            return False

    return True


def _quality_type(title: str) -> str:
    t = title.lower()
    if any(x in t for x in OEM_POSITIVE):
        return "OEM/original indicated"
    if any(x in t for x in AFTERMARKET_POSITIVE):
        return "Aftermarket/replacement indicated"
    return "Unspecified"


def _iqr_filter(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(rows) < 5:
        return rows
    vals = sorted(float(x["price"]) for x in rows)
    q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")
    iqr = q3 - q1
    if iqr <= 0:
        return rows
    lo = max(0, q1 - 1.5 * iqr)
    hi = q3 + 1.5 * iqr
    return [x for x in rows if lo <= float(x["price"]) <= hi]


def _summary(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    prices = [float(x["price"]) for x in rows]
    return {
        "count": len(prices),
        "median": round(statistics.median(prices), 2),
        "mean": round(statistics.mean(prices), 2),
        "min": round(min(prices), 2),
        "max": round(max(prices), 2),
    }


def fetch_live_component_price(
    model: str,
    component: str,
    *,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    Return current active eBay asking-price references for one component.
    Uses the median after component/model matching and IQR outlier removal.
    """
    component = _normalize_component(component)
    model_name = model_display_name(model)
    rule = _rule(component)
    query = f"{model_name} {rule['query']}"

    try:
        token = _access_token()
        r = requests.get(
            EBAY_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
            },
            params={
                "q": query,
                "filter": "conditions:{NEW|USED},priceCurrency:USD,deliveryCountry:US",
                "limit": max(1, min(int(limit), 200)),
                "auto_correct": "KEYWORD",
            },
            timeout=25,
        )
        r.raise_for_status()
        items = r.json().get("itemSummaries", []) or []

        rows = []
        for item in items:
            title = str(item.get("title", ""))
            if not _title_matches(title, model, component):
                continue
            try:
                price = float((item.get("price") or {}).get("value"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            rows.append({
                "title": title,
                "price": price,
                "currency": (item.get("price") or {}).get("currency", "USD"),
                "condition": item.get("condition"),
                "quality_type": _quality_type(title),
                "url": item.get("itemWebUrl"),
                "seller": (item.get("seller") or {}).get("username"),
            })

        raw_count = len(rows)
        rows = _iqr_filter(rows)

        if not rows:
            return {
                "ok": False,
                "model": model_name,
                "component": component,
                "query": query,
                "source": "eBay Browse API",
                "price_type": "Current active asking prices",
                "reference_value": None,
                "listing_count": 0,
                "raw_listing_count": raw_count,
                "error": "No suitable component listings found.",
                "listings": [],
            }

        overall = _summary(rows)
        oem_rows = [x for x in rows if x["quality_type"] == "OEM/original indicated"]
        aft_rows = [x for x in rows if x["quality_type"] == "Aftermarket/replacement indicated"]

        return {
            "ok": True,
            "model": model_name,
            "component": component,
            "query": query,
            "source": "eBay Browse API",
            "price_type": "Current active asking prices",
            "reference_value": overall["median"],
            "median": overall["median"],
            "mean": overall["mean"],
            "low": overall["min"],
            "high": overall["max"],
            "listing_count": overall["count"],
            "raw_listing_count": raw_count,
            "oem": _summary(oem_rows),
            "aftermarket": _summary(aft_rows),
            "listings": rows[:20],
            "error": None,
        }

    except Exception as exc:
        return {
            "ok": False,
            "model": model_name,
            "component": component,
            "query": query,
            "source": "eBay Browse API",
            "price_type": "Current active asking prices",
            "reference_value": None,
            "listing_count": 0,
            "raw_listing_count": 0,
            "error": str(exc),
            "listings": [],
        }


if st is not None:
    fetch_live_component_price_cached = st.cache_data(
        ttl=3600, show_spinner=False
    )(fetch_live_component_price)
else:
    fetch_live_component_price_cached = fetch_live_component_price


def load_fallback_config(path: Path = DEFAULT_FALLBACK_PATH) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _walk_for_model(data: Any, model_key: str) -> Optional[Any]:
    """Find a model node in either flat or nested researched config structures."""
    if isinstance(data, dict):
        if model_key in data:
            return data[model_key]
        for v in data.values():
            found = _walk_for_model(v, model_key)
            if found is not None:
                return found
    return None


def _extract_component_entries(node: Any) -> List[Dict[str, Any]]:
    if isinstance(node, list):
        return [x for x in node if isinstance(x, dict)]
    if isinstance(node, dict):
        for key in ("components", "component_values", "parts", "values"):
            if isinstance(node.get(key), list):
                return node[key]
        # Convert dict-of-components to entries.
        out = []
        for k, v in node.items():
            if isinstance(v, (int, float)):
                out.append({"component": k, "reference_value": v})
            elif isinstance(v, dict):
                e = dict(v)
                e.setdefault("component", k)
                out.append(e)
        return out
    return []


def _fallback_component(model: str, component: str) -> Optional[Dict[str, Any]]:
    data = load_fallback_config()
    key = normalize_model_key(model)
    node = _walk_for_model(data, key)
    if node is None:
        return None

    target = _normalize_component(component).lower()
    entries = _extract_component_entries(node)

    aliases = {
        "display assembly": {"display assembly", "oled display assembly", "display"},
        "rear camera assembly": {"rear camera assembly", "rear camera module", "rear camera"},
        "rear camera module": {"rear camera assembly", "rear camera module", "rear camera"},
        "front camera": {"front camera", "front camera assembly"},
        "charging port assembly": {"charging port assembly", "lightning connector assembly"},
        "wireless charging / nfc": {"wireless charging / nfc", "wireless charging antenna"},
        "speaker": {"speaker", "loudspeaker"},
    }
    accepted = aliases.get(target, {target})

    for e in entries:
        name = str(
            e.get("component")
            or e.get("component_name")
            or e.get("name")
            or ""
        ).strip().lower()
        if name not in accepted:
            continue

        value = (
            e.get("reference_value")
            or e.get("value")
            or e.get("price")
            or e.get("market_reference")
            or e.get("usd")
        )
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue

        return {
            "ok": True,
            "model": model_display_name(model),
            "component": component,
            "source": "Research component dataset",
            "price_type": "Stored replacement-part reference",
            "reference_value": round(value, 2),
            "median": round(value, 2),
            "mean": None,
            "low": None,
            "high": None,
            "listing_count": 0,
            "raw_listing_count": 0,
            "oem": None,
            "aftermarket": None,
            "listings": [],
            "used_fallback": True,
            "error": None,
        }
    return None


def get_component_market_price(
    model: str,
    component: str,
    *,
    fallback_value: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Website-facing function.

    eBay live asking-price reference -> researched JSON -> supplied fallback.
    """
    if ebay_configured():
        live = fetch_live_component_price_cached(model, component)
        if live.get("ok") and live.get("reference_value") is not None:
            live["used_fallback"] = False
            return live

    stored = _fallback_component(model, component)
    if stored:
        return stored

    if fallback_value is not None:
        return {
            "ok": True,
            "model": model_display_name(model),
            "component": component,
            "source": "Existing app value",
            "price_type": "Stored replacement-part reference",
            "reference_value": round(float(fallback_value), 2),
            "median": round(float(fallback_value), 2),
            "mean": None, "low": None, "high": None,
            "listing_count": 0, "raw_listing_count": 0,
            "oem": None, "aftermarket": None,
            "listings": [], "used_fallback": True, "error": None,
        }

    return {
        "ok": False,
        "model": model_display_name(model),
        "component": component,
        "source": "Unavailable",
        "price_type": None,
        "reference_value": None,
        "listing_count": 0,
        "used_fallback": True,
        "error": "No live or fallback component price is available.",
    }


def price_component_list(
    model: str,
    components: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Price a list of components.

    Each input may contain:
      component/component_name/name
      quantity/qty
      reference_value/value/price

    Returns table rows plus total known component market references.
    """
    rows = []
    total = 0.0

    for item in components:
        name = (
            item.get("component")
            or item.get("component_name")
            or item.get("name")
        )
        if not name:
            continue

        qty = item.get("quantity", item.get("qty", 1))
        try:
            qty = int(qty)
        except Exception:
            qty = 1

        fallback = (
            item.get("reference_value")
            or item.get("value")
            or item.get("price")
        )
        result = get_component_market_price(model, str(name), fallback_value=fallback)
        value = result.get("reference_value")

        subtotal = None
        if value is not None:
            subtotal = round(float(value) * qty, 2)
            total += subtotal

        rows.append({
            "Component": str(name),
            "Qty": qty,
            "Reference value": value,
            "Subtotal": subtotal,
            "Source": result.get("source"),
            "Basis": result.get("price_type"),
            "Listings": result.get("listing_count", 0),
            "OEM median": (result.get("oem") or {}).get("median"),
            "Aftermarket median": (result.get("aftermarket") or {}).get("median"),
            "_details": result,
        })

    return {
        "model": model_display_name(model),
        "rows": rows,
        "total_known_component_references": round(total, 2),
        "note": (
            "Component values are replacement-part market references. "
            "They are separate from whole-phone resale value, recycler payout, "
            "recoverable-material value, and CTIA grading."
        ),
    }


def render_component_market_table(
    model: str,
    components: List[Dict[str, Any]],
):
    """Optional Streamlit renderer for direct use in app.py."""
    if st is None:
        raise RuntimeError("Streamlit is not installed.")

    result = price_component_list(model, components)
    st.markdown("### Component market values")

    display_rows = []
    for row in result["rows"]:
        display_rows.append({
            "Component": row["Component"],
            "Qty": row["Qty"],
            "Reference value": (
                f"${row['Reference value']:,.2f}"
                if row["Reference value"] is not None else "Unavailable"
            ),
            "Source": row["Source"],
            "Listings": row["Listings"] if row["Listings"] else "—",
            "OEM median": (
                f"${row['OEM median']:,.2f}"
                if row["OEM median"] is not None else "—"
            ),
            "Aftermarket median": (
                f"${row['Aftermarket median']:,.2f}"
                if row["Aftermarket median"] is not None else "—"
            ),
        })

    st.dataframe(display_rows, use_container_width=True, hide_index=True)

    st.metric(
        "Total of known component market references",
        f"${result['total_known_component_references']:,.2f}",
    )

    if ebay_configured():
        st.caption(
            "Live values use filtered current eBay asking prices and are cached "
            "for one hour. OEM/aftermarket labels are inferred from listing titles."
        )
    else:
        st.caption(
            "eBay live pricing is not active yet. Values are coming from the "
            "existing researched component dataset."
        )

    st.caption(result["note"])
    return result
