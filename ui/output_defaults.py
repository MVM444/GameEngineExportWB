"""Helpers to compute and persist default export folder/name values."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Optional, Tuple

LAST_DOC_PATH_KEY = "last_doc_path"
TEMP_OUTPUT_ROOT_NAME = "GameEngineExportWB"


def _strip_to_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _normalize_base_name(candidate: str, fallback: str = "Scene") -> str:
    candidate = candidate.strip()
    candidate = _strip_to_ascii(candidate)
    candidate = re.sub(r"\s+", "_", candidate)
    candidate = re.sub(r"[^0-9A-Za-z_-]", "", candidate)
    candidate = candidate.strip("_-")
    return candidate or fallback


def _sanitize_doc_base(doc_path: Path) -> str:
    """Normalize the stem so it can safely become a base filename."""
    return _normalize_base_name(doc_path.stem)


def temporary_output_directory(unsaved_name: str = "") -> str:
    """Return a stable per-document folder under the operating-system temp path."""
    unsaved_base = _normalize_base_name(unsaved_name, "Scene")
    return str(Path(tempfile.gettempdir()) / TEMP_OUTPUT_ROOT_NAME / unsaved_base)


def compute_output_defaults(
    params, doc_path: Optional[Path], unsaved_name: str = ""
) -> Tuple[str, str, str]:
    """Return defaults isolated from unrelated documents.

    An unsaved document has no stable project identity, so it must never reuse
    the last stored project folder or base name. It receives an isolated
    temporary folder that is not persisted as a project preference.
    """
    stored_dir = params.GetString("output_dir", "").strip()
    stored_base = params.GetString("base_name", "")

    doc_key = str(doc_path) if doc_path else ""
    doc_base = _sanitize_doc_base(doc_path) if doc_path else ""

    if doc_path is None:
        unsaved_base = _normalize_base_name(unsaved_name, "Scene") if unsaved_name else ""
        return temporary_output_directory(unsaved_base), unsaved_base, ""

    if doc_path and doc_path.parent.is_dir():
        return str(doc_path.parent), doc_base, doc_key

    # A saved preference is useful only if it is valid on this computer.
    # Otherwise leave the field empty so the user can choose a folder.
    stored_path = Path(os.path.expandvars(os.path.expanduser(stored_dir))) if stored_dir else None
    fallback_dir = str(stored_path) if stored_path and stored_path.is_dir() else ""
    return fallback_dir, doc_base or stored_base, doc_key


def ensure_output_directory(value: str) -> Tuple[str, bool]:
    """Return a normalized output folder and create it only when missing."""
    raw_value = str(value or "").strip()
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
        raw_value = raw_value[1:-1].strip()
    if not raw_value:
        raise ValueError("Output folder is empty")

    normalized = os.path.normpath(os.path.expandvars(os.path.expanduser(raw_value)))
    output_path = Path(normalized)

    # Do not call mkdir for an existing cloud-synced or reparse-point directory.
    # Windows may return Access Denied instead of File Exists for that call.
    if output_path.is_dir():
        return str(output_path), False
    if output_path.exists():
        raise NotADirectoryError("Output path exists but is not a directory: " + str(output_path))

    try:
        output_path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        # Another process may have created the directory after the first check.
        if output_path.is_dir():
            return str(output_path), False
        raise
    return str(output_path), True


def persist_output_settings(
    params, output_dir: str, base_name: str, doc_path: Optional[Path]
) -> None:
    """Store output prefs and register the active document key when available."""
    if doc_path is None:
        return
    params.SetString("output_dir", output_dir or "")
    params.SetString("base_name", base_name or "")
    if doc_path:
        params.SetString(LAST_DOC_PATH_KEY, str(doc_path))


def normalize_base_name(value: str, fallback: str = "Scene") -> str:
    return _normalize_base_name(value, fallback)
