from ftplib import FTP
import hashlib
import csv
from django.db import transaction
from io import StringIO, BytesIO, TextIOWrapper
from ..models import FileAssociation, MainData
import requests
from django.utils import timezone

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


def store_csv_data(file_association: FileAssociation, content_bytes: bytes, new_hash: str, url: str = None) -> int:
    headers, rows = parse_csv_bytes_to_dicts(content_bytes, file_association)

    with transaction.atomic():
        MainData.objects.update_or_create(
            file_association=file_association,
            defaults={"data_json": {"headers": headers, "rows": rows}}
        )

        # Update metadata
        file_association.headers = headers
        file_association.last_hash = new_hash
        file_association.last_fetched_at = timezone.now()
        if url:
            file_association.file_path = url
        file_association.save(update_fields=['headers', 'last_hash', 'last_fetched_at', 'file_path'])

    return len(rows)


def parse_csv_bytes_to_dicts(csv_bytes: bytes, fa: FileAssociation, encoding='utf-8'):
    text = csv_bytes.decode(encoding, errors='replace')
    sio = StringIO(text)
    reader = list(csv.reader(sio))

    if not reader:
        return [], []

    if fa.headers:
        headers = fa.headers
        data_rows = reader
    else:
        first_row = reader[0]

        # Count cells that have at least one alphabetic character
        alpha_count = sum(any(c.isalpha() for c in cell) for cell in first_row)
        is_header = alpha_count / max(len(first_row), 1) >= 0.7

        if is_header:
            headers = [h.strip() if h else f"col_{i}" for i, h in enumerate(first_row)]
            data_rows = reader[1:]
        else:
            headers = [f"col_{i}" for i in range(len(first_row))]
            data_rows = reader

    # Build list of dictionaries
    rows = []
    for row in data_rows:
        clean_row = {headers[i]: row[i].strip() if i < len(row) else "" for i in range(len(headers))}
        rows.append(clean_row)

    return headers, rows
