import json
from typing import List
from django.conf import settings
from ttscanner.models import SymbolState, TriggeredAlert, FileAssociation

# Load system alert rules
with open(settings.BASE_DIR / "ttscanner/alert_rules.json", encoding="utf-8") as f:
    SYSTEM_ALERT_RULES = json.load(f)


# --- Helper Functions ---
def safe_float(val):
    try:
        return float(str(val).replace(",", "")) if val not in (None, "") else None
    except Exception:
        return None


def normalize_row_keys(row: dict) -> dict:
    return {k.strip().lower(): v for k, v in row.items() if k is not None}


def lookup_any(row: dict, candidates):
    lower = {k.strip().lower(): v for k, v in row.items()}
    for c in candidates:
        val = lower.get(c.lower())
        if val is not None:
            return val
    return None


def format_message(template: str, context: dict) -> str:
    try:
        return template.format(**context)
    except Exception:
        s = template
        for k, v in context.items():
            s = s.replace("{" + k + "}", str(v))
        return s


def get_algo_rules(algo):
    if not algo:
        return None
    return SYSTEM_ALERT_RULES.get(algo.algo_name) or SYSTEM_ALERT_RULES.get(algo.algo_name.replace(" ", ""))


def process_row_for_alerts(fa: FileAssociation, algo, raw_row: dict) -> List[TriggeredAlert]:
    alerts = []
    if not raw_row:
        return alerts

    row = normalize_row_keys(raw_row)
    print(f"[DEBUG] Normalized row: {row}")

    symbol = lookup_any(row, ["symbol/interval", "symbol", "sym/int", "sym", "ticker"])
    if not symbol:
        print("[DEBUG] No symbol found, skipping row")
        return alerts
    symbol = str(symbol).strip()

    state, _ = SymbolState.objects.get_or_create(file_association=fa, symbol=symbol)
    prev = state.last_row_data or {}
    prev_alert_flags = prev.get("_alert_flags", {})

    rules = get_algo_rules(algo)

    # Determine current price
    price_field_key = (algo.price_field_key or "Last").strip()
    print(f"[DEBUG] Current price field key for: {price_field_key}")
    price_val = lookup_any(row, [price_field_key, "last", "price", "close", "entry"]) 
    print(f"[DEBUG] Current price value for: {price_val}")
    current_price = safe_float(price_val)
    print(f"[DEBUG] Current price for {symbol}: {current_price}")

    # Prepare context for messages
    context = {
        "symbol": symbol,
        "entry_price": lookup_any(row, ["entry price"]) or "",
        "target1": lookup_any(row, ["target #1", "target1"]) or "",
        "target2": lookup_any(row, ["target #2", "target2"]) or "",
        "direction": lookup_any(row, ["direction"]) or "",
        "value": price_val or "",
    }

    # --- FSOptions Logic ---
    if algo.algo_name.lower() == "fsoptions":
        print(f"[DEBUG] Processing FSOptions for {symbol}")
        fs_fields = ["call level", "call strike", "put level", "put strike"]
        for f in fs_fields:
            context[f.replace(" ", "_")] = safe_float(lookup_any(row, [f]))

        fs_alerts = SYSTEM_ALERT_RULES.get("FSOptions", {}).get("alerts", [])
        for alert_def in fs_alerts:
            key = alert_def["field"].strip().lower().replace(" ", "_")
            val = context.get(key)
            trigger_above = alert_def.get("trigger_above", True)
            notified_flag = f"{key}_notified"

            if current_price is not None and val is not None:
                if trigger_above:
                    if current_price >= val and not prev_alert_flags.get(notified_flag, False):
                        alerts.append(TriggeredAlert(file_association=fa, message=format_message(alert_def["message"], context)))
                        prev_alert_flags[notified_flag] = True
                    elif current_price < val:
                        prev_alert_flags[notified_flag] = False
                else:
                    if current_price <= val and not prev_alert_flags.get(notified_flag, False):
                        alerts.append(TriggeredAlert(file_association=fa, message=format_message(alert_def["message"], context)))
                        prev_alert_flags[notified_flag] = True
                    elif current_price > val:
                        prev_alert_flags[notified_flag] = False

    # --- MENTFib Logic ---
    elif algo.algo_name.lower() == "mentfib":
        print(f"[DEBUG] Processing MENTFib for {symbol}")
        fib_trend = lookup_any(row, ["fib pivot trend"])
        bull_trigger = safe_float(lookup_any(row, ["bull fib trigger level"]))
        bear_trigger = safe_float(lookup_any(row, ["bear fib trigger level"]))
        bull_zones = [safe_float(lookup_any(row, [f"bull zone {i}"])) for i in range(1, 4)]
        bear_zones = [safe_float(lookup_any(row, [f"bear zone {i}"])) for i in range(1, 4)]

        def crossed_alert(flag, condition, msg):
            if condition and not prev_alert_flags.get(flag, False):
                alerts.append(TriggeredAlert(file_association=fa, message=msg))
                prev_alert_flags[flag] = True
            elif not condition:
                prev_alert_flags[flag] = False

        if current_price is not None and fib_trend:
            trend = fib_trend.upper()
            if trend == "BULLISH":
                crossed_alert("bull_trigger_notified", bull_trigger is not None and current_price >= bull_trigger,
                              f"{symbol}: Bull Fib Trigger Level crossed above {bull_trigger}")
                for i, zone in enumerate(bull_zones, 1):
                    crossed_alert(f"bull_zone{i}_notified", zone is not None and current_price >= zone,
                                  f"{symbol}: Bull Zone {i} crossed {zone}")
            elif trend == "BEARISH":
                crossed_alert("bear_trigger_notified", bear_trigger is not None and current_price <= bear_trigger,
                              f"{symbol}: Bear Fib Trigger Level crossed below {bear_trigger}")
                for i, zone in enumerate(bear_zones, 1):
                    crossed_alert(f"bear_zone{i}_notified", zone is not None and current_price <= zone,
                                  f"{symbol}: Bear Zone {i} crossed {zone}")

    # --- Generic TTScanner / Price Zone / Direction Change Logic ---
    elif rules and "trigger_type" in rules:
        print(f"[DEBUG] Processing generic rules for {symbol}")
        trigger_type = rules["trigger_type"].lower()
        alert_defs = {a["field"].strip().lower(): a for a in rules.get("alerts", [])}

        for field in rules.get("fields", []):
            field_key = field.strip().lower()
            level_val = safe_float(lookup_any(row, [field]))
            notified_flag = f"{field_key}_notified"
            prev_notified = prev_alert_flags.get(notified_flag, False)

            if level_val is None:
                continue

            trigger_alert = False

            if trigger_type == "price_zone" and current_price is not None:
                if current_price >= level_val and not prev_notified:
                    trigger_alert = True
                elif current_price < level_val:
                    prev_alert_flags[notified_flag] = False

            elif trigger_type == "direction_change":
                current_dir = lookup_any(row, ["direction"])
                prev_dir = prev.get("last_direction")
                if current_dir and current_dir != prev_dir:
                    trigger_alert = True
                    prev["last_direction"] = current_dir

            if trigger_alert:
                alert_msg = alert_defs.get(field_key, {}).get("message", "{field} triggered for {symbol}")
                alerts.append(TriggeredAlert(file_association=fa, message=format_message(alert_msg, context)))
                prev_alert_flags[notified_flag] = True
                print(f"[ALERT] {symbol}: {alert_msg}")

    prev["_alert_flags"] = prev_alert_flags
    prev.update({k: v for k, v in row.items() if k not in ["last_direction"]}) 
    state.last_row_data = prev
    if current_price is not None:
        state.last_price = current_price
    if prev.get("last_direction"):
        state.last_direction = prev["last_direction"]
    state.save()
    print(f"[DEBUG] Saved state for {symbol}: {state.last_row_data}")

    return alerts











# import json
# from django.conf import settings
# from typing import List
# from ttscanner.models import SymbolState, TriggeredAlert, FileAssociation
# from django.utils import timezone


# with open(settings.BASE_DIR / "ttscanner/alert_rules.json", encoding="utf-8") as f:
#     SYSTEM_ALERT_RULES = json.load(f)


# def safe_float(val):
#     try:
#         if val is None or val == "":
#             return None
#         return float(str(val).replace(",", ""))
#     except Exception:
#         return None


# def normalize_row_keys(row: dict) -> dict:
#     """Return shallow copy of row with lowercase trimmed keys and original values."""
#     return {k.strip().lower(): v for k, v in row.items() if k is not None}


# def lookup_any(row: dict, candidates):
#     """Return first present value from row for given candidate names (case-insensitive)."""
#     lower = {k.strip().lower(): v for k, v in row.items()}
#     for c in candidates:
#         val = lower.get(c.lower())
#         if val is not None:
#             return val
#     return None


# def format_message(template: str, context: dict) -> str:
#     """Format message template with context keys (safe)."""
#     try:
#         return template.format(**context)
#     except Exception:
#         s = template
#         for k, v in context.items():
#             s = s.replace("{" + k + "}", str(v))
#         return s


# def get_algo_rules(algo):
#     """Return rule dict for given algo name (or None)."""
#     if not algo:
#         return None
#     return SYSTEM_ALERT_RULES.get(algo.algo_name) or SYSTEM_ALERT_RULES.get(algo.algo_name.replace(" ", ""))


# def process_row_for_alerts(fa: FileAssociation, algo, raw_row: dict) -> List[TriggeredAlert]:
#     alerts = []
#     if not raw_row:
#         return alerts

#     row = {k.strip().lower(): v for k, v in raw_row.items()}

#     symbol = lookup_any(row, ["symbol/interval", "symbol", "sym/int", "sym", "ticker"])
#     if not symbol:
#         return alerts

#     symbol = str(symbol).strip()
#     state, _ = SymbolState.objects.get_or_create(file_association=fa, symbol=symbol)

#     rules = get_algo_rules(algo)
#     price_field_key = (algo.price_field_key or "Last").strip()
#     price_val = lookup_any(row, [price_field_key, price_field_key.lower(), price_field_key.title(), "last", "price", "close"])
#     current_price = safe_float(price_val)

#     context = {
#         "symbol": symbol,
#         "entry_price": row.get("Entry Price") or row.get("entry price") or "",
#         "target1": row.get("Target #1") or row.get("Target1") or row.get("target1") or "",
#         "target2": row.get("Target #2") or row.get("Target2") or row.get("target2") or "",
#         "direction": row.get("Direction") or row.get("direction") or "",
#         "value": price_val or "",
#     }
#     prev = state.last_row_data or {}

#     if not rules:
#         prev_dir = prev.get("Direction") or prev.get("direction")
#         cur_dir = row.get("Direction") or row.get("direction")
#         if prev_dir and cur_dir and str(prev_dir).strip().upper() != str(cur_dir).strip().upper():
#             template = "📌 New {direction} position opened for {symbol} at {entry_price}"
#             msg = format_message(template, context)
#             alerts.append(TriggeredAlert(file_association=fa, message=msg))
#     else:
#         trigger_type = rules.get("trigger_type")
#         fields = rules.get("fields", [])
#         alerts_def = rules.get("alerts", [])
#         alerts_map = {a["field"].strip().lower(): a for a in alerts_def}

#         if trigger_type == "state_change":
#             for field in fields:
#                 field_key_lower = field.strip().lower()
#                 cur_val = lookup_any(row, [field, field.lower(), field.replace(" ", ""), field.replace("#", "#")])
#                 prev_val = prev.get(field) or prev.get(field.lower()) or prev.get(field.replace(" ", ""))

#                 if field_key_lower in ("profit %", "profit%", "profit"):
#                     cur_num = safe_float(cur_val)
#                     prev_num = safe_float(prev_val)
#                     if prev_num is not None and cur_num is not None and cur_num != prev_num:
#                         alert_tmpl = alerts_map.get(field_key_lower, {}).get("message", "💰 Profit crossed {value}% for {symbol}")
#                         context["value"] = cur_num
#                         msg = format_message(alert_tmpl, context)
#                         alerts.append(TriggeredAlert(file_association=fa, message=msg))

#                 elif field_key_lower in ("target #1", "target #1".lower(), "target1"):
#                     target_raw = lookup_any(row, ["Target #1", "Target1", "target1"])
#                     target_num = safe_float(target_raw)
#                     prev_target_raw = prev.get("Target #1") or prev.get("target1")
#                     if target_num is not None and not state.target1_hit and current_price is not None:
#                         direction = (row.get("Direction") or row.get("direction") or prev.get("Direction") or "").strip().lower()
#                         hit = False
#                         if direction in ("long", "buy", "bullish", "bull"):
#                             hit = current_price >= target_num
#                         elif direction in ("short", "sell", "bearish", "bear"):
#                             hit = current_price <= target_num
#                         else:
#                             hit = current_price >= target_num

#                         if hit:
#                             alert_tmpl = alerts_map.get(field_key_lower, {}).get("message", "🎯 Target #1 hit for {symbol} at {target1}")
#                             context["target1"] = target_raw
#                             msg = format_message(alert_tmpl, context)
#                             alerts.append(TriggeredAlert(file_association=fa, message=msg))
#                             state.target1_hit = True

#                 elif field_key_lower in ("target #2", "target2"):
#                     target_raw = lookup_any(row, ["Target #2", "Target2", "target2"])
#                     target_num = safe_float(target_raw)
#                     if target_num is not None and not state.target2_hit and current_price is not None:
#                         direction = (row.get("Direction") or row.get("direction") or prev.get("Direction") or "").strip().lower()
#                         hit = False
#                         if direction in ("long", "buy", "bullish", "bull"):
#                             hit = current_price >= target_num
#                         elif direction in ("short", "sell", "bearish", "bear"):
#                             hit = current_price <= target_num
#                         else:
#                             hit = current_price >= target_num

#                         if hit:
#                             alert_tmpl = alerts_map.get(field_key_lower, {}).get("message", "🎯 Target #2 hit for {symbol} at {target2}")
#                             context["target2"] = target_raw
#                             msg = format_message(alert_tmpl, context)
#                             alerts.append(TriggeredAlert(file_association=fa, message=msg))
#                             state.target2_hit = True

#                 else:
#                     if prev_val is not None and cur_val is not None and str(prev_val).strip() != str(cur_val).strip():
#                         alert_tmpl = alerts_map.get(field_key_lower, {}).get("message", "{field} changed for {symbol}")
#                         context.update({
#                             "value": cur_val,
#                             "old_value": prev_val,
#                             "field": field
#                         })
#                         msg = format_message(alert_tmpl, context)
#                         alerts.append(TriggeredAlert(file_association=fa, message=msg))

#         elif trigger_type == "price_cross":
#             for field in fields:
#                 cur_val = lookup_any(row, [field])
#                 cur_num = safe_float(cur_val)
#                 prev_num = safe_float(prev.get(field)) if prev else None

#                 if prev_num is not None and cur_num is not None and current_price is not None:
#                     if prev_num < cur_num and current_price >= cur_num and prev.get(field + "_notified") != True:
#                         alert_tmpl = (alerts_map.get(field.lower(), {}) or {}).get("message")
#                         context["value"] = cur_val
#                         msg = format_message(alert_tmpl or f"{field} crossed at {{value}} for {{symbol}}", context)
#                         alerts.append(TriggeredAlert(file_association=fa, message=msg))
#                         prev[field + "_notified"] = True

#                     if current_price is not None and current_price < cur_num:
#                         prev[field + "_notified"] = False

#         elif trigger_type == "price_zone":
#             for field in fields:
#                 prev_zone_val = prev.get(field)
#                 cur_zone_val = lookup_any(row, [field])
#                 if prev_zone_val is None:
#                     pass
#                 else:
#                     if cur_zone_val is not None and str(prev_zone_val).strip() != str(cur_zone_val).strip():
#                         alert_tmpl = alerts_map.get(field.strip().lower(), {}).get("message")
#                         context.update({"value": cur_zone_val, "field": field})
#                         msg = format_message(alert_tmpl or f"{symbol} moved into {field}: {{value}}", context)
#                         alerts.append(TriggeredAlert(file_association=fa, message=msg))

#                 prev[field] = cur_zone_val

#     state.last_row_data = row
#     if current_price is not None:
#         state.last_price = current_price
#     dir_val = row.get("Direction") or row.get("direction") or prev.get("Direction")
#     if dir_val:
#         state.last_direction = dir_val

#     state.last_alerts = state.last_alerts or {}
#     state.save()
#     return alerts
