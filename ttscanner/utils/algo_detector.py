from ttscanner.models import Algo
import csv, io, json
from django.conf import settings

with open(settings.BASE_DIR / "ttscanner" / "alert_rules.json", encoding="utf-8") as f:
    SYSTEM_ALERT_RULES = json.load(f)

class UnknownAlgoError(Exception):
    pass

ALGO_PRICE_FIELD_MAP = {
    "FSOptions": "entry price",     
    "TTScanner": "entry price",     
    "MENTFib": "last price"             
}

ALGO_SIGNATURE_MAP = {
    "FSOptions": {"call level", "put level", "call strike", "put strike", "trend dir"},
    "TTScanner": {"direction", "entry price", "stop price", "profit", "target #1"},
    "MENTFib": {"bull zone 1", "bull zone 2", "bear zone 1", "bear zone 2", "fib pivot trend"}
}

def extract_csv_headers(csv_bytes: bytes):
    try:
        decoded = csv_bytes.decode("utf-8")
    except UnicodeDecodeError:
        decoded = csv_bytes.decode("latin-1")
    reader = csv.reader(io.StringIO(decoded))
    headers = next(reader, None)
    return [h.strip() for h in headers] if headers else []

def detect_algo(headers: list[str]) -> str:
    headers_lower = set([h.lower().strip() for h in headers])
    best_match = None
    best_score = 0

    for algo, signature in ALGO_SIGNATURE_MAP.items():
        matched = len(headers_lower.intersection(signature))
        score = matched / len(signature)
        if score > best_score:
            best_score = score
            best_match = algo

    return best_match if best_score >= 0.4 else "Unknown"

def assign_detected_algo(fa, csv_bytes):
    headers = extract_csv_headers(csv_bytes)
    fa.headers = headers

    algo_name = detect_algo(headers)
    if algo_name == "Unknown":
        fa.algo = None
        fa.status = "unknown"
        fa._price_field = None
        fa.system_alert_rules = {}
        fa.save(update_fields=["algo", "status", "headers"])
        return "Unknown"

    try:
        algo_obj = Algo.objects.get(algo_name=algo_name)
        fa.algo = algo_obj
        fa.status = "active"
        fa._price_field = ALGO_PRICE_FIELD_MAP.get(algo_name)
        fa.system_alert_rules = SYSTEM_ALERT_RULES.get(algo_name, {})
        fa.save(update_fields=["algo", "status", "headers"])
        return algo_name
    except Algo.DoesNotExist:
        fa.algo = None
        fa.status = "unknown"
        fa._price_field = None
        fa.system_alert_rules = {}
        fa.save(update_fields=["algo", "status", "headers"])
        return "Unknown"
