import json, re
from typing import List
from django.conf import settings
from ttscanner.models import SymbolState, TriggeredAlert, FileAssociation

with open(settings.BASE_DIR / "ttscanner/alert_rules.json", encoding="utf-8") as f:
    SYSTEM_ALERT_RULES = json.load(f)

def safe_float(val):
    try:
        return float(str(val).replace(",", "")) if val not in (None, "") else None
    except Exception:
        return None
    

def lookup_any(row: dict, candidates):
    lower = {k.strip().lower(): v for k, v in row.items()}
    for c in candidates:
        val = lower.get(c.lower())
        if val is not None:
            return val
    return None


def get_algo_rules(algo):
    if not algo:
        return None
    return SYSTEM_ALERT_RULES.get(algo.algo_name) or SYSTEM_ALERT_RULES.get(algo.algo_name.replace(" ", ""))


def normalize_row_keys(row: dict) -> dict:
    return {k.strip().lower(): v for k, v in row.items() if k is not None}


def format_message(template: str, context: dict) -> str:
    try:
        return template.format(**context)
    except Exception:
        s = template
        for k, v in context.items():
            s = s.replace("{" + k + "}", str(v))
        return s


def extract_symbol_from_row(row: dict) -> str | None:
    for key, value in row.items():
        if not value:
            continue

        normalized = key.lower().replace(" ", "").replace("/", "")

        if normalized in {"symbol", "sym", "symint", "ticker", "symbolinterval"}:
            symbol = str(value).strip().upper()
            if symbol:
                return symbol

    return None



def process_row_for_alerts(fa, algo, raw_row: dict) -> List[TriggeredAlert]:
    alerts = []

    # Skip non-ttscanner files
    if "ttscanner" not in fa.file_name.lower():
        print(f"[SYSTEM] Skipping non-ttscanner file: {fa.file_name}")
        return alerts

    print(f"\n[SYSTEM] Processing row for file: {fa.file_name}")

    if not raw_row:
        print("[SYSTEM] Empty row received → skipping")
        return alerts

    # Skip initial import
    if getattr(fa, "data_version", 1) == 0:
        print("[SYSTEM] data_version = 0 → skipping alerts")
        return alerts

    # Normalize row
    row = {k.strip(): v for k, v in raw_row.items() if k is not None}
    print(f"[SYSTEM] Row keys: {list(row.keys())}")

    # Extract symbol
    symbol = extract_symbol_from_row(row)
    if not symbol:
        print("[SYSTEM] Symbol NOT FOUND in row → skipping")
        return alerts

    print(f"[SYSTEM] Processing symbol: {symbol}")

    # Load symbol state
    state, _ = SymbolState.objects.get_or_create(
        file_association=fa,
        symbol=symbol
    )

    prev = state.last_row_data or {}
    fired_map = getattr(state, "last_triggered_alerts", None) or getattr(state, "last_alerts", {}) or {}
    direction_field = next((k for k in row if "direction" in k.lower()), None)
    target_fields = [
        k for k in row
        if "target" in k.lower() and ("date" in k.lower() or "datetime" in k.lower())
    ]

    print(f"[SYSTEM] Direction field: {direction_field}")
    print(f"[SYSTEM] Target fields: {target_fields}")

    # Load rules
    system_rules = (
        SYSTEM_ALERT_RULES.get(algo.algo_name)
        or SYSTEM_ALERT_RULES.get(algo.algo_name.replace(" ", ""))
    )

    print(f"[SYSTEM] Rules for algo '{algo.algo_name}': {system_rules}")

    if not system_rules:
        print("[SYSTEM] No rules found → skipping")
        return alerts

    # Detect direction change
    direction_changed = (
        direction_field
        and prev.get(direction_field) != row.get(direction_field)
    )

    if direction_changed:
        print("[SYSTEM] Direction changed → resetting fired alerts")
        fired_map = {}

    for alert_config in system_rules.get("alerts", []):
        template = alert_config.get("message", "")
        placeholders = re.findall(r"{(.*?)}", template)
        values = {}

        for ph in placeholders:
            ph_norm = re.sub(r"[\/_\-\s]", "", ph.lower())
            match = next(
                (v for k, v in row.items()
                 if re.sub(r"[\/_\-\s]", "", k.lower()) == ph_norm),
                ""
            )
            values[ph] = match

        values.setdefault("symbol", symbol)
        values.setdefault(
            "price",
            row.get("price") or row.get("last") or row.get("entry")
        )
        values.setdefault("entry", row.get("entry"))
        values.setdefault("direction", row.get(direction_field))

        # Determine trigger
        should_trigger = False

        for tf in target_fields:
            if prev.get(tf) != row.get(tf):
                print(f"[SYSTEM] Target changed: {tf}")
                should_trigger = True

        if direction_changed:
            print("[SYSTEM] Direction change trigger")
            should_trigger = True

        # Deduplication
        alert_signature = {
            "direction": row.get(direction_field),
            "targets": {tf: row.get(tf) for tf in target_fields}
        }

        alert_key = template

        if fired_map.get(alert_key) == alert_signature:
            print("[SYSTEM] Duplicate alert skipped")
            continue

        if should_trigger and values:
            message = template.format(**values)

            print(f"[SYSTEM ALERT] {message}")

            alerts.append(
                TriggeredAlert(
                    file_association=fa,
                    alert_source="system",
                    message=message
                )
            )

            fired_map[alert_key] = alert_signature

    # Persist state
    state.last_row_data = row
    state.last_price = row.get("last") or row.get("price") or row.get("entry")
    state.last_triggered_alerts = fired_map
    state.save(update_fields=[
        "last_row_data",
        "last_price",
        "last_alerts"
    ])
    print(f"[SYSTEM] Finished processing {symbol}, alerts fired: {len(alerts)}")

    return alerts



































# def process_row_for_alerts(fa: FileAssociation, algo, raw_row: dict) -> List[TriggeredAlert]:
#     from ttscanner.models import SymbolState, TriggeredAlert

#     alerts = []
#     if not raw_row:
#         return alerts

#     row = {k.strip().lower(): v for k, v in raw_row.items() if k is not None}
#     symbol = row.get("symbol") or row.get("ticker")
#     if not symbol:
#         return alerts
#     symbol = str(symbol).strip()

#     state, _ = SymbolState.objects.get_or_create(file_association=fa, symbol=symbol)
#     prev = state.last_row_data or {}
#     prev_alert_flags = prev.get("_alert_flags", {})

#     price_val = row.get("last") or row.get("price") or row.get("entry")
#     try:
#         current_price = float(str(price_val).replace(",", ""))
#     except Exception:
#         current_price = None

#     if current_price is None:
#         return alerts

#     target_keys = [k for k in row.keys() if re.match(r"^(target\s*#?\d+|tgt\d+)$", k, re.IGNORECASE)]
#     for t in target_keys:
#         target_val = row.get(t)
#         if target_val is None:
#             continue
#         try:
#             target_price = float(str(target_val).replace(",", ""))
#         except Exception:
#             continue

#         flag_name = f"{t}_hit"
#         if current_price >= target_price and not prev_alert_flags.get(flag_name, False):
#             alerts.append(
#                 TriggeredAlert(
#                     file_association=fa,
#                     alert_source="system",
#                     message=f"{symbol}: {t} reached at {current_price}"
#                 )
#             )
#             print("Target Hit")
#             prev_alert_flags[flag_name] = True
#         elif current_price < target_price:
#             prev_alert_flags[flag_name] = False

#     prev["_alert_flags"] = prev_alert_flags
#     state.last_row_data = prev
#     state.last_price = current_price
#     state.save()

#     return alerts
