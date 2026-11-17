import json
import os
import re
import uuid

import pandas as pd
from flask import current_app

from app.extensions import db
from app.models.recipient import Recipient, RecipientList

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

TARGET_FIELDS = ("email_address", "first_name", "last_name", "custom", "ignore")

_EMAIL_HINTS = ("email", "e-mail", "mail")
_FIRST_NAME_HINTS = ("first_name", "firstname", "first name", "given name", "fname")
_LAST_NAME_HINTS = ("last_name", "lastname", "last name", "surname", "lname")


def guess_mapping(columns: list[str]) -> dict:
    """Best-effort default column -> target field mapping, by column name."""
    mapping = {}
    for col in columns:
        key = col.strip().lower()
        if any(hint in key for hint in _EMAIL_HINTS):
            mapping[col] = "email_address"
        elif any(hint in key for hint in _FIRST_NAME_HINTS):
            mapping[col] = "first_name"
        elif any(hint in key for hint in _LAST_NAME_HINTS):
            mapping[col] = "last_name"
        else:
            mapping[col] = "ignore"
    return mapping


def _tmp_dir() -> str:
    path = os.path.join(current_app.instance_path, "tmp_uploads")
    os.makedirs(path, exist_ok=True)
    return path


def _tmp_path(upload_token: str) -> str:
    matches = [
        f for f in os.listdir(_tmp_dir()) if f.startswith(upload_token + ".")
    ]
    if not matches:
        raise FileNotFoundError(f"No temp upload found for token {upload_token}")
    return os.path.join(_tmp_dir(), matches[0])


def save_upload(file_storage) -> str:
    """Saves the uploaded CSV/XLSX to a temp path, returns an upload_token."""
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        raise ValueError("Only .csv, .xlsx, or .xls files are supported.")
    token = uuid.uuid4().hex
    path = os.path.join(_tmp_dir(), f"{token}{ext}")
    file_storage.save(path)
    return token


def _read_dataframe(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, dtype=str, keep_default_na=False)
    return df.fillna("")


def read_columns(upload_token: str) -> dict:
    """Returns {"columns": [...], "sample_rows": [...], "row_count": N}."""
    path = _tmp_path(upload_token)
    df = _read_dataframe(path)
    return {
        "columns": list(df.columns),
        "sample_rows": df.head(5).to_dict(orient="records"),
        "row_count": len(df),
    }


def preview_import(upload_token: str, mapping: dict) -> dict:
    """
    mapping: {column_name: target_field}. Returns validation summary + first
    20 mapped rows, without writing to the DB.
    """
    path = _tmp_path(upload_token)
    df = _read_dataframe(path)
    rows = _map_rows(df, mapping)

    seen_emails = set()
    valid = duplicate = invalid = 0
    for row in rows:
        email = row["email_address"].strip().lower()
        if not EMAIL_RE.match(email):
            invalid += 1
        elif email in seen_emails:
            duplicate += 1
        else:
            seen_emails.add(email)
            valid += 1

    return {
        "total_count": len(rows),
        "valid_count": valid,
        "duplicate_count": duplicate,
        "invalid_count": invalid,
        "preview_rows": rows[:20],
    }


def _map_rows(df: pd.DataFrame, mapping: dict) -> list[dict]:
    custom_columns = [col for col, target in mapping.items() if target == "custom"]
    email_col = next((col for col, target in mapping.items() if target == "email_address"), None)
    first_name_col = next((col for col, target in mapping.items() if target == "first_name"), None)
    last_name_col = next((col for col, target in mapping.items() if target == "last_name"), None)

    rows = []
    for _, record in df.iterrows():
        rows.append(
            {
                "email_address": (record.get(email_col, "") if email_col else "").strip(),
                "first_name": (record.get(first_name_col, "") if first_name_col else "").strip(),
                "last_name": (record.get(last_name_col, "") if last_name_col else "").strip(),
                "custom_fields": {col: record.get(col, "") for col in custom_columns},
            }
        )
    return rows


def commit_import(upload_token: str, mapping: dict, list_name: str, source_filename: str, uploaded_by_id):
    """Parses the temp file again, writes RecipientList + Recipient rows, cleans up the temp file."""
    path = _tmp_path(upload_token)
    df = _read_dataframe(path)
    rows = _map_rows(df, mapping)

    recipient_list = RecipientList(
        name=list_name.strip(),
        source_filename=source_filename,
        uploaded_by=uploaded_by_id,
    )
    db.session.add(recipient_list)
    db.session.flush()  # assign recipient_list.id

    seen_emails = set()
    valid = duplicate = invalid = 0
    for row in rows:
        email = row["email_address"].strip().lower()
        is_valid = bool(EMAIL_RE.match(email))
        is_duplicate = is_valid and email in seen_emails

        if not is_valid:
            invalid += 1
        elif is_duplicate:
            duplicate += 1
            continue  # don't insert duplicates
        else:
            seen_emails.add(email)
            valid += 1

        db.session.add(
            Recipient(
                list_id=recipient_list.id,
                email_address=row["email_address"].strip(),
                first_name=row["first_name"] or None,
                last_name=row["last_name"] or None,
                custom_fields=json.dumps(row["custom_fields"]) if row["custom_fields"] else None,
                is_valid_format=1 if is_valid else 0,
            )
        )

    recipient_list.total_count = len(rows)
    recipient_list.valid_count = valid
    recipient_list.duplicate_count = duplicate
    recipient_list.invalid_count = invalid
    db.session.commit()

    try:
        os.remove(path)
    except OSError:
        pass

    return recipient_list
