from ftplib import FTP
import hashlib, csv, json, uuid
from django.db import transaction
from io import StringIO, BytesIO, TextIOWrapper
from ..models import FileAssociation, MainData, Algo
from django.utils import timezone
import re
from typing import List, Dict

def compute_hash_bytes(content_bytes: bytes) -> str:
    h = hashlib.sha256()
    h.update(content_bytes)
    return h.hexdigest()


def read_uploaded_file_bytes(uploaded_file):
    uploaded_file.seek(0)
    return uploaded_file.read()



# def fetch_url_bytes(url: str, timeout=10):
#     resp = requests.get(url, timeout=timeout)

#     content = resp.content
#     resp.raise_for_status()
#     if content.startswith(b"<html") or content.startswith(b"<!DOCTYPE html"):
#         raise ValueError("The URL returned HTML, not CSV. Use a direct CSV download link.")
    
#     return resp.content


def fetch_ftp_bytes(file_path):
    FTP_HOST = "ftp.ment.com"
    FTP_USER = "Laiba@ment.com"  
    FTP_PASS = "MentPunch2025Laiba"

    try:
        ftp = FTP(FTP_HOST, timeout=30)
        ftp.set_pasv(True) 
        ftp.login(user=FTP_USER, passwd=FTP_PASS)
        print(f"Connected to FTP Server: {FTP_HOST}")

        buffer = BytesIO()
        ftp.retrbinary(f"RETR {file_path}", buffer.write)
        ftp.quit()
        return buffer.getvalue()

    except Exception as e:
        print(f"{e} Error Occured While Connecting")
        raise


def is_file_changed(file_association: FileAssociation, content_bytes: bytes) -> bool:
    new_hash = compute_hash_bytes(content_bytes)
    changed = not (file_association.last_hash and file_association.last_hash == new_hash)
    return changed, new_hash


def fetch_and_store_file(file_association):
    content_bytes = fetch_ftp_bytes(file_association.file_path) 
    changed, new_hash = is_file_changed(file_association, content_bytes)

    if changed:
        rows_count = store_csv_data(file_association, content_bytes, new_hash)
        print(f"File updated. {rows_count} rows stored.")
    else:
        print("No changes detected.")


def get_stable_key(row: dict) -> tuple:
    """
    Generate a stable key for a row by dynamically finding fields
    containing 'sym' and 'int' in their names.
    """
    sym_value = None
    int_value = None
    for key, value in row.items():
        if value is None:
            continue
        key_lower = key.lower()
        if "sym" in key_lower:
            sym_value = str(value).strip().lower()
        if "int" in key_lower:
            int_value = str(value).strip().lower()
    return (sym_value, int_value)


def store_csv_data(file_association: FileAssociation, content_bytes: bytes, new_hash: str, url: str = None) -> int:
    headers, rows = parse_csv_bytes_to_dicts(content_bytes, file_association)

    existing_rows_by_key = {}
    if existing_main_data := MainData.objects.filter(file_association=file_association).first():
        for r in existing_main_data.data_json.get("rows", []):
            key = get_stable_key(r)
            existing_rows_by_key[key] = r.get("_row_id")

    file_algo_name = file_association.algo.algo_name if file_association.algo else "Auto-Detect"
    algo_config = Algo.objects.filter(algo_name=file_algo_name).first()

    supports_targets = algo_config.supports_targets if algo_config else True
    supports_direction = algo_config.supports_direction if algo_config else True
    supports_volume = algo_config.supports_volume_alerts if algo_config else False
    price_field = algo_config.price_field_key if algo_config else "Last"

    # Process rows and assign _row_id
    for row in rows:
        key = get_stable_key(row)
        # Preserve old _row_id if exists, otherwise create new
        row["_row_id"] = existing_rows_by_key.get(key, str(uuid.uuid4()))
        row["_supports_targets"] = supports_targets
        row["_supports_direction"] = supports_direction
        row["_supports_volume"] = supports_volume
        row["_price_field"] = price_field
        # Compute row hash
        row["_row_hash"] = MainData.compute_row_hash(row)

    # Save MainData and FileAssociation metadata
    with transaction.atomic():
        MainData.objects.update_or_create(
            file_association=file_association,
            defaults={"data_json": {"headers": headers, "rows": rows}}
        )

        file_association.headers = headers
        file_association.last_hash = new_hash
        file_association.last_fetched_at = timezone.now()
        if url:
            file_association.file_path = url
        file_association.save(update_fields=['headers', 'last_hash', 'last_fetched_at', 'file_path'])

    return len(rows)


# def store_csv_data(file_association: FileAssociation, content_bytes: bytes, new_hash: str, url: str = None) -> int:
#     headers, rows = parse_csv_bytes_to_dicts(content_bytes, file_association)

#     file_algo_name = file_association.algo.algo_name if file_association.algo else "Auto-Detect"
#     algo_config = Algo.objects.filter(algo_name=file_algo_name).first()

#     supports_targets = algo_config.supports_targets if algo_config else True
#     supports_direction = algo_config.supports_direction if algo_config else True
#     supports_volume = algo_config.supports_volume_alerts if algo_config else False
#     price_field = algo_config.price_field_key if algo_config else "Last"

#     for row in rows:
#         row["_supports_targets"] = supports_targets
#         row["_supports_direction"] = supports_direction
#         row["_supports_volume"] = supports_volume
#         row["_price_field"] = price_field

#     with transaction.atomic():
#         MainData.objects.update_or_create(
#             file_association=file_association,
#             defaults={"data_json": {"headers": headers, "rows": rows}}
#         )

#         file_association.headers = headers
#         file_association.last_hash = new_hash
#         file_association.last_fetched_at = timezone.now()
#         if url:
#             file_association.file_path = url
#         file_association.save(update_fields=['headers', 'last_hash', 'last_fetched_at', 'file_path'])

#     return len(rows)


def parse_csv_bytes_to_dicts(csv_bytes: bytes, fa: FileAssociation, encoding='utf-8'):
    text = csv_bytes.decode(encoding, errors='replace')
    sio = StringIO(text)
    reader = csv.DictReader(sio)

    if not reader.fieldnames:
        return [], []

    raw_headers = [h.strip() for h in reader.fieldnames]

    rows = []
    for row in reader:
        clean_row = {}
        for h_original, h_clean in zip(reader.fieldnames, raw_headers):
            value = row.get(h_original, "")
            value = value.strip() if value else ""
            clean_row[h_clean] = value
        rows.append(clean_row)

    return raw_headers, rows



