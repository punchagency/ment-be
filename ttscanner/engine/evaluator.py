import json, re
from datetime import datetime
from typing import List
from collections import defaultdict
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


def get_row_value(row: dict, key: str) -> str:
    """Get value from row, trying multiple key variations"""
    # Try exact match first
    if key in row:
        return str(row[key])
    
    # Try case-insensitive
    for k, v in row.items():
        if k.lower() == key.lower():
            return str(v)
    
    # Try partial match (remove spaces, #, etc)
    clean_key = key.replace(" ", "").replace("#", "").replace("_", "").lower()
    for k, v in row.items():
        clean_k = k.replace(" ", "").replace("#", "").replace("_", "").lower()
        if clean_k == clean_key:
            return str(v)
    
    return ""


def group_alerts_by_symbol(alerts_data):
    symbol_groups = defaultdict(list)
    for alert in alerts_data:
        symbol = alert.get("symbol")
        if symbol:
            symbol_groups[symbol].append(alert)
    
    # Create combined messages for each symbol
    combined_messages = []
    
    for symbol, alerts in symbol_groups.items():
        if len(alerts) == 1:
            # Single alert for this symbol
            combined_messages.append({
                "symbol": symbol,
                "message": alerts[0]["message"],
                "alert_type": alerts[0].get("alert_type", "")
            })
        else:
            # Multiple alerts - combine intelligently
            combined = combine_symbol_alerts(symbol, alerts)
            combined_messages.append({
                "symbol": symbol,
                "message": combined,
                "alert_type": "combined"
            })
    
    return combined_messages


def combine_symbol_alerts(symbol, alerts):
    direction_alerts = []
    target1_alerts = []
    target2_alerts = []
    other_alerts = []
    
    # Store the full messages for targets to extract prices
    target1_full_messages = []
    target2_full_messages = []
    
    for alert in alerts:
        message = alert["message"]
        alert_type = alert.get("alert_type", "").lower()
        
        if "direction" in alert_type:
            direction_alerts.append(message)
        elif "target #1" in alert_type:
            target1_alerts.append(message)
            target1_full_messages.append(message)
        elif "target #2" in alert_type:
            target2_alerts.append(message)
            target2_full_messages.append(message)
        else:
            other_alerts.append(message)
    
    parts = []
    
    # Handle direction alerts
    if direction_alerts:
        if len(direction_alerts) == 1:
            dir_msg = direction_alerts[0]
            if f"for {symbol}" in dir_msg:
                parts.append(dir_msg)
            else:
                parts.append(f"{symbol}: {dir_msg}")
        else:
            directions = set()
            for msg in direction_alerts:
                if "LONG" in msg:
                    directions.add("LONG")
                elif "SHORT" in msg:
                    directions.add("SHORT")
            if directions:
                parts.append(f"{symbol}: Position changed to {', '.join(directions)}")
    
    # Handle target alerts WITH PRICE INFORMATION
    target_parts = []
    
    # Extract price from target #1 messages
    if target1_alerts:
        price = extract_target_price(target1_full_messages[0]) if target1_full_messages else ""
        if price:
            target_parts.append(f"🎯 Target #1 hit at {price}")
        else:
            target_parts.append("Target #1 hit")
    
    # Extract price from target #2 messages  
    if target2_alerts:
        price = extract_target_price(target2_full_messages[0]) if target2_full_messages else ""
        if price:
            target_parts.append(f"🎯 Target #2 hit at {price}")
        else:
            target_parts.append("Target #2 hit")
    
    if target_parts:
        if len(target_parts) == 1:
            parts.append(f"{symbol}: {target_parts[0]}")
        else:
            parts.append(f"{symbol}: {', '.join(target_parts)}")

    if other_alerts:
        if len(other_alerts) == 1:
            parts.append(other_alerts[0])
        else:
            other_summary = f"{symbol}: Multiple alerts"
            parts.append(other_summary)
    
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        if parts[0].startswith(f"{symbol}:") and parts[1].startswith(f"{symbol}:"):
            msg1 = parts[0].replace(f"{symbol}:", "").strip()
            msg2 = parts[1].replace(f"{symbol}:", "").strip()
            return f"{symbol}: {msg1} | {msg2}"
        else:
            return f"{parts[0]} | {parts[1]}"
    else:
        summary_parts = []
        for part in parts:
            if f"{symbol}:" in part:
                summary_parts.append(part.replace(f"{symbol}:", "").strip())
            else:
                summary_parts.append(part)
        
        if summary_parts:
            return f"{symbol}: " + " | ".join(summary_parts)
        else:
            return f"{symbol}: Multiple alerts triggered"


def extract_target_price(message):
    price_patterns = [
        r'at\s+([\d,]+\.\d+)',  
        r'@\s+([\d,]+\.\d+)',  
        r'→\s+([\d,]+\.\d+)',  
    ]
    
    for pattern in price_patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1)
    
    decimal_match = re.search(r'([\d,]+\.\d+)', message)
    if decimal_match:
        return decimal_match.group(1)
    
    return ""

def process_row_for_alerts(fa, algo, raw_row: dict) -> List[TriggeredAlert]:
    alerts = []

    if "ttscanner" not in fa.file_name.lower():
        print(f"[SYSTEM] Skipping non-ttscanner file: {fa.file_name}")
        return alerts

    print(f"\n[SYSTEM] Processing row for file: {fa.file_name}")

    if not raw_row:
        print("[SYSTEM] Empty row received → skipping")
        return alerts

    # ========== SKIP ALERTS ON INITIAL UPLOAD ==========
    if getattr(fa, "data_version", 1) == 0:
        print("[SYSTEM] data_version = 0 → INITIAL UPLOAD, skipping all alerts")
        return alerts

    row = {k.strip(): v for k, v in raw_row.items() if k is not None}
    print(f"[SYSTEM] Row keys: {list(row.keys())}")

    symbol = extract_symbol_from_row(row)
    if not symbol:
        print("[SYSTEM] Symbol NOT FOUND in row → skipping")
        return alerts

    print(f"[SYSTEM] Processing symbol: {symbol}")

    state, _ = SymbolState.objects.get_or_create(
        file_association=fa,
        symbol=symbol
    )

    prev = state.last_row_data or {}
    fired_map = getattr(state, "last_triggered_alerts", {})
    direction_field = next((k for k in row if "direction" in k.lower()), None)
    target_datetime_fields = [
        k for k in row
        if "target" in k.lower() and ("date" in k.lower() or "datetime" in k.lower())
    ]

    print(f"[SYSTEM] Direction field: {direction_field}")
    print(f"[SYSTEM] Target datetime fields: {target_datetime_fields}")

    # Load rules
    system_rules = SYSTEM_ALERT_RULES.get("TTScanner")
    if not system_rules:
        print("[SYSTEM] No rules found → skipping")
        return alerts

    # ========== DEBUG: SEE WHAT'S CHANGING ==========
    print(f"[DEBUG] Previous Direction: '{prev.get(direction_field, '')}'")
    print(f"[DEBUG] Current Direction: '{row.get(direction_field, '')}'")
    
    for tf in target_datetime_fields:
        print(f"[DEBUG] Target '{tf}': prev='{prev.get(tf, '')}' curr='{row.get(tf, '')}'")

    # ========== CHECK FOR INITIAL STATE (NO PREVIOUS DATA) ==========
    # If this is the first time we're seeing this symbol, skip alerts
    # because we don't know what "changed" from
    if not prev:
        print(f"[SYSTEM] First time processing {symbol} → skipping alerts (no previous state)")
        # Still save the state for next time
        state.last_row_data = row
        state.save()
        return alerts

    # ========== DETECT CHANGES ==========
    direction_changed = False
    current_direction = row.get(direction_field, "")
    
    if direction_field and prev.get(direction_field, "") != current_direction:
        direction_changed = True
        print(f"[CHANGE] Direction changed: '{prev.get(direction_field, '')}' → '{current_direction}'")
        
        # Reset ALL fired alerts when direction changes (new position)
        fired_map = {}
        print(f"[RESET] Cleared fired alerts for new position")
    
    # Track which target datetimes changed (and their values)
    target_changes = {}
    for tf in target_datetime_fields:
        prev_val = prev.get(tf, "")
        curr_val = row.get(tf, "")
        
        # Special case: If previous was None/empty and this is first data after upload
        # We should treat it as initial state, not a change
        if not prev and not prev_val and curr_val:
            print(f"[SKIP] Initial target value after upload → not treating as change")
            continue
            
        if prev_val != curr_val:
            # Extract target number
            match = re.search(r'#?(\d+)', tf, re.IGNORECASE)
            target_num = match.group(1) if match else "1"
            target_key = f"target{target_num}"
            
            # Store both the field and the actual datetime value
            target_changes[target_key] = {
                "field": tf,
                "value": curr_val,
                "prev_value": prev_val
            }
            
            print(f"[CHANGE] Target #{target_num} datetime changed: '{prev_val}' → '{curr_val}'")

    # ========== COLLECT ALERTS DATA (FOR GROUPING) ==========
    alerts_data = []  # Collect alert data before grouping
    
    for alert_config in system_rules.get("alerts", []):
        template = alert_config.get("message", "")
        alert_field = alert_config.get("field", "").lower()
        
        print(f"[ALERT] Processing: {alert_field}")

        # ========== CHECK TRIGGER CONDITIONS ==========
        should_trigger = False
        
        # DIRECTION ALERTS
        if "direction" in alert_field and direction_changed:
            # Only alert on REAL trading directions (not FLAT)
            if current_direction in ["LONG", "SHORT"]:
                should_trigger = True
                print(f"[TRIGGER] Direction alert: {current_direction} position opened")
        
        # TARGET ALERTS
        elif "target" in alert_field:
            target_num = "1" if "target #1" in alert_field.lower() else "2"
            target_key = f"target{target_num}"
            
            # Check ALL conditions:
            # 1. Target datetime changed from empty to non-empty (target hit)
            # 2. We're in a trading position (LONG/SHORT)
            # 3. Target price is actually set
            # 4. We have previous state to compare against (not initial upload)
            
            if target_key in target_changes:
                change_info = target_changes[target_key]
                prev_val = change_info["prev_value"]
                curr_val = change_info["value"]
                
                # Condition 1: Changed from empty to non-empty (target just hit)
                if not prev_val and curr_val:
                    # Condition 2: Must be in trading position
                    if current_direction in ["LONG", "SHORT"]:
                        # Condition 3: Target price must be set
                        price_field = f"Target #{target_num}"
                        target_price = row.get(price_field, "")
                        
                        if target_price and target_price != "":
                            should_trigger = True
                            print(f"[TRIGGER] Target #{target_num} hit at {curr_val}")
        
        if not should_trigger:
            print(f"[SKIP] No trigger for {alert_field}")
            continue
        
        # ========== FILL TEMPLATE ==========
        values = {
            "symbol": symbol,
            "direction": current_direction,
            "entry_price": row.get("Entry Price", ""),
            "target1": row.get("Target #1", ""),
            "target #1": row.get("Target #1", ""),
            "target2": row.get("Target #2", ""),
            "target #2": row.get("Target #2", ""),
        }
        
        # Create message
        message = template
        for key, val in values.items():
            placeholder = "{" + key + "}"
            if placeholder in message:
                message = message.replace(placeholder, str(val))
        
        print(f"[ALERT FIRED] {message}")
        
        # ========== DEDUPLICATION ==========
        # Create unique key based on WHAT actually changed
        if "direction" in alert_field:
            # For direction: symbol + direction value
            alert_key = f"{symbol}_direction_{current_direction}"
        elif "target" in alert_field:
            # For target: symbol + target# + datetime value
            target_num = "1" if "target #1" in alert_field.lower() else "2"
            target_field = f"Target #{target_num} DateTime"
            target_value = row.get(target_field, "")
            alert_key = f"{symbol}_target{target_num}_{target_value}"
        
        print(f"[DEDUPE] Checking key: {alert_key}")
        
        if alert_key in fired_map:
            print(f"[DUPLICATE] Already fired {alert_key} → SKIPPING")
            continue
        
        # ========== STORE ALERT DATA FOR GROUPING ==========
        alerts_data.append({
            "symbol": symbol,
            "message": message,
            "alert_type": alert_field,
            "alert_key": alert_key,
            "timestamp": datetime.now()
        })
        
        # Mark as fired
        fired_map[alert_key] = datetime.now().isoformat()
        print(f"[STORED] Alert stored with key: {alert_key}")

    # ========== GROUP ALERTS BY SYMBOL ==========
    if alerts_data:
        grouped_alerts = group_alerts_by_symbol(alerts_data)
        
        for grouped_alert in grouped_alerts:
            alerts.append(
                TriggeredAlert(
                    file_association=fa,
                    alert_source="system",
                    message=grouped_alert["message"],
                    symbol=grouped_alert["symbol"]  # Store symbol for reference
                )
            )
        
        print(f"[GROUPING] {len(alerts_data)} individual alerts grouped into {len(grouped_alerts)} messages")
    else:
        print(f"[GROUPING] No alerts to group for {symbol}")

    # ========== CLEANUP OLD ALERTS ==========
    # Remove alerts older than 1 day to prevent map from growing forever
    current_time = datetime.now()
    keys_to_remove = []
    for key, timestamp_str in fired_map.items():
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            if (current_time - timestamp).days > 1:
                keys_to_remove.append(key)
        except:
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del fired_map[key]
    
    if keys_to_remove:
        print(f"[CLEANUP] Removed {len(keys_to_remove)} old alert records")

    state.last_row_data = row
    state.last_triggered_alerts = fired_map
    state.save()
    
    print(f"[SYSTEM] Finished processing {symbol}, alerts created: {len(alerts)}")
    
    return alerts





































# import json, re
# from typing import List
# from django.conf import settings
# from ttscanner.models import SymbolState, TriggeredAlert, FileAssociation

# with open(settings.BASE_DIR / "ttscanner/alert_rules.json", encoding="utf-8") as f:
#     SYSTEM_ALERT_RULES = json.load(f)

# def safe_float(val):
#     try:
#         return float(str(val).replace(",", "")) if val not in (None, "") else None
#     except Exception:
#         return None
    

# def lookup_any(row: dict, candidates):
#     lower = {k.strip().lower(): v for k, v in row.items()}
#     for c in candidates:
#         val = lower.get(c.lower())
#         if val is not None:
#             return val
#     return None


# def get_algo_rules(algo):
#     if not algo:
#         return None
#     return SYSTEM_ALERT_RULES.get(algo.algo_name) or SYSTEM_ALERT_RULES.get(algo.algo_name.replace(" ", ""))


# def normalize_row_keys(row: dict) -> dict:
#     return {k.strip().lower(): v for k, v in row.items() if k is not None}


# def format_message(template: str, context: dict) -> str:
#     try:
#         return template.format(**context)
#     except Exception:
#         s = template
#         for k, v in context.items():
#             s = s.replace("{" + k + "}", str(v))
#         return s


# def extract_symbol_from_row(row: dict) -> str | None:
#     for key, value in row.items():
#         if not value:
#             continue

#         normalized = key.lower().replace(" ", "").replace("/", "")

#         if normalized in {"symbol", "sym", "symint", "ticker", "symbolinterval"}:
#             symbol = str(value).strip().upper()
#             if symbol:
#                 return symbol

#     return None



# def process_row_for_alerts(fa, algo, raw_row: dict) -> List[TriggeredAlert]:
#     alerts = []

#     # Skip non-ttscanner files
#     if "ttscanner" not in fa.file_name.lower():
#         print(f"[SYSTEM] Skipping non-ttscanner file: {fa.file_name}")
#         return alerts

#     print(f"\n[SYSTEM] Processing row for file: {fa.file_name}")

#     if not raw_row:
#         print("[SYSTEM] Empty row received → skipping")
#         return alerts

#     # Skip initial import
#     if getattr(fa, "data_version", 1) == 0:
#         print("[SYSTEM] data_version = 0 → skipping alerts")
#         return alerts

#     # Normalize row
#     row = {k.strip(): v for k, v in raw_row.items() if k is not None}
#     print(f"[SYSTEM] Row keys: {list(row.keys())}")

#     # Extract symbol
#     symbol = extract_symbol_from_row(row)
#     if not symbol:
#         print("[SYSTEM] Symbol NOT FOUND in row → skipping")
#         return alerts

#     print(f"[SYSTEM] Processing symbol: {symbol}")

#     # Load symbol state
#     state, _ = SymbolState.objects.get_or_create(
#         file_association=fa,
#         symbol=symbol
#     )

#     prev = state.last_row_data or {}
#     fired_map = getattr(state, "last_triggered_alerts", None) or getattr(state, "last_alerts", {}) or {}
#     direction_field = next((k for k in row if "direction" in k.lower()), None)
#     target_fields = [
#         k for k in row
#         if "target" in k.lower() and ("date" in k.lower() or "datetime" in k.lower())
#     ]

#     print(f"[SYSTEM] Direction field: {direction_field}")
#     print(f"[SYSTEM] Target fields: {target_fields}")

#     # Load rules
#     system_rules = (
#         SYSTEM_ALERT_RULES.get(algo.algo_name)
#         or SYSTEM_ALERT_RULES.get(algo.algo_name.replace(" ", ""))
#     )

#     print(f"[SYSTEM] Rules for algo '{algo.algo_name}': {system_rules}")

#     if not system_rules:
#         print("[SYSTEM] No rules found → skipping")
#         return alerts

#     # Detect direction change
#     direction_changed = (
#         direction_field
#         and prev.get(direction_field) != row.get(direction_field)
#     )

#     if direction_changed:
#         print("[SYSTEM] Direction changed → resetting fired alerts")
#         fired_map = {}

#     for alert_config in system_rules.get("alerts", []):
#         template = alert_config.get("message", "")
#         print(f"[SYSTEM] Processing alert template: {template}")
#         placeholders = re.findall(r"{(.*?)}", template)
#         print(f"[SYSTEM] Placeholders found: {placeholders}")
#         values = {}

#         for ph in placeholders:
#             ph_norm = re.sub(r"[\/_\-\s]", "", ph.lower())
#             match = next(
#                 (v for k, v in row.items()
#                  if re.sub(r"[\/_\-\s]", "", k.lower()) == ph_norm),
#                 ""
#             )
#             values[ph] = match

#         values.setdefault("symbol", symbol)
#         values.setdefault(
#             "price",
#             row.get("price") or row.get("last") or row.get("entry")
#         )
#         values.setdefault("entry", row.get("entry"))
#         values.setdefault("direction", row.get(direction_field))

#         # Determine trigger
#         should_trigger = False

#         for tf in target_fields:
#             if prev.get(tf) != row.get(tf):
#                 print(f"[SYSTEM] Target changed: {tf}")
#                 should_trigger = True

#         if direction_changed:
#             print("[SYSTEM] Direction change trigger")
#             should_trigger = True

#         # Deduplication
#         alert_signature = {
#             "direction": row.get(direction_field),
#             "targets": {tf: row.get(tf) for tf in target_fields}
#         }

#         alert_key = template

#         if fired_map.get(alert_key) == alert_signature:
#             print("[SYSTEM] Duplicate alert skipped")
#             continue

#         if should_trigger and values:
#             message = template.format(**values)

#             print(f"[SYSTEM ALERT] {message}")

#             alerts.append(
#                 TriggeredAlert(
#                     file_association=fa,
#                     alert_source="system",
#                     message=message
#                 )
#             )

#             fired_map[alert_key] = alert_signature

#     # Persist state
#     state.last_row_data = row
#     state.last_price = row.get("last") or row.get("price") or row.get("entry")
#     state.last_triggered_alerts = fired_map
#     state.save(update_fields=[
#         "last_row_data",
#         "last_price",
#         "last_alerts"
#     ])
#     print(f"[SYSTEM] Finished processing {symbol}, alerts fired: {len(alerts)}")

#     return alerts




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
