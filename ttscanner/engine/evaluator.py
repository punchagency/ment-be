import json, re, logging
from datetime import datetime
from typing import List
from collections import defaultdict
from django.conf import settings
from ttscanner.models import SymbolState, TriggeredAlert, FileAssociation

logger = logging.getLogger(__name__)

# DON'T load JSON here - wait until first use
_SYSTEM_ALERT_RULES = None

def get_alert_rules():
    """Load JSON only when needed"""
    global _SYSTEM_ALERT_RULES
    if _SYSTEM_ALERT_RULES is None:
        # Load with proper encoding
        with open(settings.BASE_DIR / "ttscanner/alert_rules.json", 'r', encoding='utf-8') as f:
            _SYSTEM_ALERT_RULES = json.load(f)
    return _SYSTEM_ALERT_RULES

def safe_float(val):
    try:
        return float(str(val).replace(",", "")) if val not in (None, "") else None
    except Exception:
        return None

def normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "").replace("/", "").replace("_", "")

def lookup_any(row: dict, candidates: List[str]):
    normalized_row = {normalize_key(k): v for k, v in row.items() if k is not None}
    for c in candidates:
        val = normalized_row.get(normalize_key(c))
        if val is not None:
            return val
    return None

def extract_symbol_from_row(row: dict) -> str | None:
    candidates = ["symbol", "sym", "symint", "ticker", "symbolinterval"]
    symbol = lookup_any(row, candidates)
    return str(symbol).upper() if symbol else None

def group_alerts_by_symbol(alerts_data):
    symbol_groups = defaultdict(list)
    for alert in alerts_data:
        symbol = alert.get("symbol")
        if symbol:
            symbol_groups[symbol].append(alert)

    combined_messages = []
    for symbol, alerts in symbol_groups.items():
        if len(alerts) == 1:
            combined_messages.append({
                "symbol": symbol,
                "message": alerts[0]["message"],
                "alert_type": alerts[0].get("alert_type", "")
            })
        else:
            combined = combine_symbol_alerts(symbol, alerts)
            combined_messages.append({
                "symbol": symbol,
                "message": combined,
                "alert_type": "combined"
            })
    return combined_messages

def combine_symbol_alerts(symbol, alerts):
    messages = [alert["message"] for alert in alerts]
    return f"{symbol}: " + " | ".join(messages)

def detect_new_trade(row: dict, fired_map: dict) -> List[dict]:
    alerts_data = []

    symbol = extract_symbol_from_row(row)
    if not symbol:
        print("Skipping row: no symbol found")
        return []

    bars_raw = lookup_any(row, ["Bars Since Entry", "BarSinceEntry", "BarsSinceEntry"])
    direction = (lookup_any(row, ["Direction", "Trade Direction"]) or "").strip().upper()
    entry_price = lookup_any(row, ["Entry Price", "EntryPrice"]) or ""

    if not (isinstance(bars_raw, str) and bars_raw.strip().upper() == "NEW"):
        print(f"{symbol}: Bars Since Entry is not 'NEW' ({bars_raw}), skipping new trade")
        return []

    if direction not in ["LONG", "SHORT"]:
        print(f"{symbol}: Invalid direction ({direction}), skipping new trade")
        return []

    alert_key = f"{symbol}_newtrade_{direction}"
    if alert_key in fired_map:
        print(f"{symbol}: Alert already fired ({alert_key}), skipping")
        return []

    # FIXED LINE: Use get_alert_rules() instead of SYSTEM_ALERT_RULES
    system_alerts = get_alert_rules().get("TTScanner", {}).get("alerts", [])
    message_template = None
    for alert_cfg in system_alerts:
        if normalize_key(alert_cfg.get("field")) == normalize_key("Bars Since Entry"):
            if direction in alert_cfg["message"]:
                message_template = alert_cfg["message"]
                break

    if not message_template:
        message_template = f"🟢 New LONG position for {{Sym/Int}} at ${{Entry Price}}" if direction=="LONG" else f"🔴 New SHORT position for {{Sym/Int}} at ${{Entry Price}}"

    message = message_template.replace("{Sym/Int}", symbol).replace("{Entry Price}", str(entry_price)).replace("{Bars Since Entry}", str(bars_raw))

    fired_map[alert_key] = datetime.now().isoformat()

    alerts_data.append({
        "symbol": symbol,
        "message": message,
        "alert_type": "new_trade",
        "alert_key": alert_key,
        "timestamp": datetime.now(),
    })

    print(f"New trade detected: {message}")
    return alerts_data

def detect_flat_trade(row: dict, prev_row: dict, fired_map: dict) -> List[dict]:
    alerts_data = []

    symbol = extract_symbol_from_row(row)
    if not symbol or not prev_row:
        return []

    prev_direction = (lookup_any(prev_row, ["Direction"]) or "").strip().upper()
    curr_direction = (lookup_any(row, ["Direction"]) or "").strip().upper()

    if "FLAT" not in curr_direction or prev_direction not in ["LONG", "SHORT"]:
        return []

    alert_key = f"{symbol}_flat_{prev_direction}"
    if alert_key in fired_map:
        return []

    profit_factor = safe_float(lookup_any(row, ["Profit Factor", "ProfitFactor", "PF"]))
    profit_str = str(profit_factor) if profit_factor is not None else "N/A"

    # FIXED LINE: Use get_alert_rules() instead of SYSTEM_ALERT_RULES
    system_alerts = get_alert_rules().get("TTScanner", {}).get("alerts", [])
    message_template = None
    for alert_cfg in system_alerts:
        if normalize_key(alert_cfg.get("field")) == normalize_key("Direction"):
            if prev_direction in alert_cfg["message"]:
                message_template = alert_cfg["message"]
                break
    if not message_template:
        message_template = f"🚫 [FLAT] {{Sym/Int}} | {prev_direction} position closed | Return: {{Profit Factor}}"

    message = message_template.replace("{Sym/Int}", symbol).replace("{Profit Factor}", str(profit_str))

    fired_map[alert_key] = datetime.now().isoformat()
    alerts_data.append({
        "symbol": symbol,
        "message": message,
        "alert_type": "flat_close",
        "alert_key": alert_key,
        "timestamp": datetime.now(),
    })

    print(message)
    return alerts_data

def detect_reversal_trade(row: dict, prev_row: dict, fired_map: dict) -> List[dict]:
    alerts_data = []

    symbol = extract_symbol_from_row(row)
    if not symbol or not prev_row:
        return []

    prev_dir = (lookup_any(prev_row, ["Direction"]) or "").strip().upper()
    curr_dir = (lookup_any(row, ["Direction"]) or "").strip().upper()

    if prev_dir == curr_dir:
        return []

    valid_reversals = {("LONG", "SHORT"), ("SHORT", "LONG")}
    if (prev_dir, curr_dir) not in valid_reversals:
        return []

    alert_key = f"{symbol}_reversal_{prev_dir}_to_{curr_dir}"
    if alert_key in fired_map:
        return []

    # FIXED LINE: Use get_alert_rules() instead of SYSTEM_ALERT_RULES
    system_alerts = get_alert_rules().get("TTScanner", {}).get("alerts", [])
    message_template = None
    for alert_cfg in system_alerts:
        if normalize_key(alert_cfg.get("field")) == normalize_key("Direction"):
            if f"{prev_dir}→{curr_dir}" in alert_cfg["message"]:
                message_template = alert_cfg["message"]
                break
    if not message_template:
        message_template = f"🔄 {prev_dir}→{curr_dir} reversal for {{Sym/Int}}"

    message = message_template.replace("{Sym/Int}", symbol)
    fired_map[alert_key] = datetime.now().isoformat()
    alerts_data.append({
        "symbol": symbol,
        "message": message,
        "alert_type": "reversal",
        "alert_key": alert_key,
        "timestamp": datetime.now(),
    })

    print(message)
    return alerts_data

def detect_target_hit(row: dict, state: SymbolState, fired_map: dict) -> List[dict]:
    alerts_data = []

    logger.debug(f"🔍 detect_target_hit called for row keys: {list(row.keys())}")
    logger.debug(f"🔍 Row sample values: { {k: v for i, (k, v) in enumerate(row.items()) if i < 5} }")
    
    symbol = extract_symbol_from_row(row)
    if not symbol:
        logger.warning(f"❌ Could not extract symbol from row: {row.get('symbol', 'N/A')}")
        return []
    
    logger.info(f"🎯 Checking targets for symbol: {symbol}")
    logger.debug(f"🎯 Current state: target1_hit={getattr(state, 'target1_hit', False)}, target2_hit={getattr(state, 'target2_hit', False)}")
    
    # Define targets to check
    targets = [
        {"field": "Target #1", "hit_flag": "target1_hit"},
        {"field": "Target #2", "hit_flag": "target2_hit"}
    ]
    
    # Log available target fields in the row
    available_target_fields = [field for field in ["Target #1", "Target #2"] if field in row]
    logger.debug(f"🎯 Available target fields in row: {available_target_fields}")
    logger.debug(f"🎯 Target #1 value: {row.get('Target #1', 'NOT FOUND')}")
    logger.debug(f"🎯 Target #2 value: {row.get('Target #2', 'NOT FOUND')}")
    
    for target in targets:
        target_field = target["field"]
        hit_flag = target["hit_flag"]
        
        # Check if target field exists in row
        if target_field not in row:
            logger.debug(f"📭 Target field '{target_field}' not found in row for {symbol}")
            continue
        
        # Get target value
        target_value = lookup_any(row, [target_field])
        logger.debug(f"🎯 Target '{target_field}' value for {symbol}: {target_value} (type: {type(target_value)})")
        
        # Check if already hit
        already_hit = getattr(state, hit_flag, False)
        logger.debug(f"🎯 Already hit '{target_field}'? {already_hit}")
        
        # Skip if already hit
        if already_hit:
            logger.info(f"⏭️ Target '{target_field}' already hit for {symbol}, skipping")
            continue
        
        # Check if target has valid value
        if not target_value:
            logger.debug(f"📭 Target '{target_field}' has no value for {symbol}")
            continue
        
        # Try to convert target value to float for numeric check
        try:
            target_float = float(target_value)
            logger.debug(f"🔢 Target '{target_field}' numeric value: {target_float}")
        except (ValueError, TypeError):
            logger.warning(f"⚠️ Target '{target_field}' value '{target_value}' is not numeric for {symbol}")
            continue
        
        # FIXED LINE: Use get_alert_rules() instead of SYSTEM_ALERT_RULES
        message_template = None
        system_alerts = get_alert_rules().get("TTScanner", {}).get("alerts", [])
        logger.debug(f"📋 Available system alerts: {len(system_alerts)}")
        
        for alert_cfg in system_alerts:
            alert_field = normalize_key(alert_cfg.get("field", ""))
            target_field_norm = normalize_key(target_field)
            logger.debug(f"  Comparing: alert_field='{alert_field}' vs target_field='{target_field_norm}'")
            
            if alert_field == target_field_norm:
                message_template = alert_cfg.get("message")
                logger.debug(f"✅ Found message template for {target_field}: {message_template}")
                break
        
        # Default message template if not found
        if not message_template:
            message_template = f"📊 {target_field}: {{Sym/Int}} hit at ${{{target_field}}} | Profit: {{Profit %}}%"
            logger.debug(f"📝 Using default message template for {target_field}")
        
        # Get profit percentage
        profit_pct = safe_float(lookup_any(row, ["Profit %", "Profit%", "Profit", "Profit_Pct"]))
        
        # Build message
        message = message_template.replace("{Sym/Int}", symbol)
        message = message.replace(f"{{{target_field}}}", str(target_value))
        
        # Handle profit placeholder
        if "{Profit %}" in message:
            profit_display = f"{profit_pct:.2f}" if profit_pct is not None else "N/A"
            message = message.replace("{Profit %}", profit_display)
        elif "{Profit}" in message:
            profit_display = f"{profit_pct:.2f}" if profit_pct is not None else "N/A"
            message = message.replace("{Profit}", profit_display)
        
        logger.info(f"✅ Target hit detected! {symbol} - {target_field} = {target_value} (Profit: {profit_pct})")
        
        # Create alert key and store in fired map
        alert_key = f"{symbol}_{target_field.replace(' ', '').lower()}"
        current_time = datetime.now().isoformat()
        fired_map[alert_key] = current_time
        logger.debug(f"🗝️ Alert key: {alert_key}, timestamp: {current_time}")
        
        # Create alert data
        alert_data = {
            "symbol": symbol,
            "message": message,
            "alert_type": "target_hit",
            "alert_key": alert_key,
            "target_field": target_field,
            "target_value": target_value,
            "profit_pct": profit_pct,
            "timestamp": datetime.now(),
        }
        alerts_data.append(alert_data)
        
        # Update state
        setattr(state, hit_flag, True)
        logger.info(f"📝 Updated state: {hit_flag}=True for {symbol}")
        
        # Print message (console output)
        print(f"🎯 [TARGET HIT] {message}")
    
    logger.info(f"📊 detect_target_hit completed for {symbol}. Alerts generated: {len(alerts_data)}")
    return alerts_data

def process_row_for_alerts(fa: FileAssociation, algo, raw_row: dict) -> List[TriggeredAlert]:
    alerts = []
    if "ttscanner" not in fa.file_name.lower() or not raw_row or getattr(fa, "data_version", 1) == 0:
        return alerts

    row = {k.strip(): v for k, v in raw_row.items() if k is not None}
    symbol = extract_symbol_from_row(row)
    if not symbol:
        return alerts

    state, _ = SymbolState.objects.get_or_create(file_association=fa, symbol=symbol)
    fired_map = getattr(state, "last_alerts", {}) or {}
    prev_row = state.last_row_data

    for detector in [detect_flat_trade, detect_new_trade]:
        for alert in detector(row, prev_row, fired_map) if detector != detect_new_trade else detector(row, fired_map):
            alerts.append(
                TriggeredAlert(
                    file_association=fa,
                    alert_source="system",
                    symbol=alert["symbol"],
                    message=alert["message"],
                )
            )

    for alert in detect_target_hit(row, state, fired_map):
        alerts.append(
            TriggeredAlert(
                file_association=fa,
                alert_source="system",
                symbol=alert["symbol"],
                message=alert["message"],
            )
        )

    state.last_row_data = row
    state.last_alerts = fired_map
    state.save()

    return alerts