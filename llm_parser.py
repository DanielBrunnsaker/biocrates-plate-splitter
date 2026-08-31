"""LLM-assisted (Ollama) extraction of sample rows from unstructured paste/upload input."""
from __future__ import annotations

import io
import json
import os
from typing import List, Optional, Tuple

import pandas as pd
import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
REQUEST_TIMEOUT = 120  # seconds — local inference can be slow on CPU
MAX_INPUT_CHARS = 40_000  # soft cap so we don't blow past small local context windows

REQUIRED_FIELDS = (
    "sample_id", "study_id", "repeat_pair", "factor_1", "factor_2",
    "material", "sample_description",
)

_SYSTEM_PROMPT = """You are a data-extraction assistant for a lab sample-tracking tool.

You will be given raw text — this may be pasted spreadsheet cells, or the flattened \
content of an Excel workbook (possibly several sheets, possibly with irregular layout, \
notes, merged headers, or inconsistent column naming). Extract every individual \
biological sample as one row with these fields:

- sample_id: unique identifier for the sample (required — skip rows with none)
- study_id: which study/cohort/project the sample belongs to (required — if the data is \
  organized by sheet and a sheet clearly represents one study, use that sheet's name; if \
  everything belongs to one obvious study, use a short label for it)
- repeat_pair: a group label for repeat/duplicate/paired measurements of the SAME \
  underlying sample (e.g. visit 1 / visit 2, technical replicates). CRITICAL: every \
  sample in the same pair/group must share the EXACT SAME repeat_pair value (e.g. both \
  rows get "pair1") — never put one sample's own sample_id in another sample's \
  repeat_pair field. Invent a short shared label per group if the source data doesn't \
  already have one (e.g. "pair1", "pair2", ...). Use "" if not applicable.
- factor_1: a stratification variable if one is present (e.g. sex, treatment arm, \
  disease status, timepoint). Use "" if none.
- factor_2: a second, independent stratification variable if one is present. Use "" if \
  none — do not repeat factor_1 here.
- material: the sample matrix / biological material (e.g. Plasma, Serum, Urine, DBS, \
  Cell culture supernatant). Use "" if not stated.
- sample_description: any other free-text description of the sample (e.g. visit label, \
  cohort note). Use "" if none.

Respond with ONLY a JSON object of this exact shape, no markdown fences, no commentary:
{"rows": [{"sample_id": "...", "study_id": "...", "repeat_pair": "...", "factor_1": "...", "factor_2": "...", "material": "...", "sample_description": "..."}]}
"""


def is_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        return r.ok
    except requests.exceptions.RequestException:
        return False


def list_models() -> List[str]:
    """Return installed Ollama model names, or [] if the server isn't reachable."""
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))
    except requests.exceptions.RequestException:
        return []


def excel_bytes_to_text(decoded: bytes) -> str:
    """Flatten every sheet of an Excel workbook into a plain-text block for the LLM,
    preserving raw layout (no header assumptions) since the sheet may be unstructured."""
    xls = pd.ExcelFile(io.BytesIO(decoded))
    parts = []
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name, header=None, dtype=str).fillna("")
        parts.append(f"### Sheet: {sheet_name}")
        for _, row in df.iterrows():
            cells = [str(c).strip() for c in row.tolist()]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _truncate(text: str) -> Tuple[str, bool]:
    if len(text) <= MAX_INPUT_CHARS:
        return text, False
    return text[:MAX_INPUT_CHARS], True


def _call_ollama(model: str, content: str) -> dict:
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "format": "json",
            "stream": False,
            "think": False,  # reasoning models: skip the "thinking" pass — faster,
                              # and avoids a garbled-content artifact seen with it on
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    raw = resp.json()["message"]["content"]
    obj = _extract_json_rows(raw)
    if obj is None:
        raise json.JSONDecodeError("No JSON object found in model output", raw, 0)
    return obj


def _extract_json_rows(raw: str) -> Optional[dict]:
    """Ollama's format='json' only guarantees *a* JSON value came out. Some local
    models occasionally prepend a stray garbled fragment before the real object
    (observed with a quantized/MLX build even with thinking disabled). Scan for the
    first JSON object in the string that actually has the {"rows": [...]} shape we
    asked for, falling back to the first JSON object found at all."""
    decoder = json.JSONDecoder()
    raw = raw.strip()
    fallback = None
    for pos, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(raw, pos)
        except json.JSONDecodeError:
            continue
        if fallback is None:
            fallback = obj
        if isinstance(obj, dict) and isinstance(obj.get("rows"), list):
            return obj
    return fallback


def parse_with_llm(text: str, model: str) -> Tuple[List[dict], str]:
    """
    Extract sample rows from arbitrary raw text via a local Ollama model.
    Returns (records, status_message). records is [] on failure.
    """
    if not model:
        return [], "No Ollama model selected — pick one in Settings → AI-assisted parsing."
    if not text or not text.strip():
        return [], "Nothing to parse."

    content, truncated = _truncate(text.strip())

    try:
        parsed = _call_ollama(model, content)
    except requests.exceptions.ConnectionError:
        return [], (
            f"Could not reach Ollama at {OLLAMA_HOST}. Is it running? "
            f"(try `ollama serve` in a terminal)"
        )
    except requests.exceptions.Timeout:
        return [], f"Ollama request timed out after {REQUEST_TIMEOUT}s — try a smaller input or a faster model."
    except requests.exceptions.RequestException as exc:
        return [], f"Ollama request failed: {exc}"
    except (KeyError, json.JSONDecodeError) as exc:
        return [], f"Model did not return valid JSON: {exc}"

    rows = parsed.get("rows") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        return [], "Model response was JSON but not in the expected {'rows': [...]} shape."

    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("sample_id", "") or "").strip()
        stud = str(row.get("study_id", "") or "").strip()
        if not sid or not stud:
            continue
        records.append({
            "sample_id": sid,
            "study_id": stud,
            "repeat_pair": str(row.get("repeat_pair", "") or "").strip(),
            "factor_1": str(row.get("factor_1", "") or "").strip(),
            "factor_2": str(row.get("factor_2", "") or "").strip(),
            "material": str(row.get("material", "") or "").strip(),
            "sample_description": str(row.get("sample_description", "") or "").strip(),
        })

    msg = f"AI parsed {len(records)} rows using '{model}'."
    if truncated:
        msg += f" Input was truncated to {MAX_INPUT_CHARS} characters — some rows may be missing."
    if not records:
        msg = f"AI ('{model}') did not extract any valid rows — check the input or try a different model."
    return records, msg
