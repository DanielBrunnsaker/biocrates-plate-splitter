"""Biocrates MetIDQ 'Sample List' CSV export — one CSV per plate, bundled as a zip."""
from __future__ import annotations

import csv
import io
import zipfile
from typing import Dict, List

from algorithm import Plate, SAMPLE_POSITIONS

SAMPLE_LIST_COLUMNS = [
    "Sample Identifier",
    "Sample Alias",  # not a standard Biocrates/WebIDQ column — inserted here as an
                      # alternate ID right next to Sample Identifier.
    "Sample description",
    "Material",
    "Species",
    "Sample attributes",
    "Cell extr. Volume",
    "User category (optional)",
    "Contact",
    "Org. info.",
]


def _plate_rows(
    plate: Plate,
    study_meta: Dict[str, Dict[str, str]],
    globals_: Dict[str, str],
) -> List[List[str]]:
    rows = []
    for pos in SAMPLE_POSITIONS:  # column-major, matches physical loading order
        w = plate.wells[pos]
        if w.well_type != "sample":
            continue
        # Species / Sample attributes are set once per study (Settings tab); Material
        # and Sample description come straight from the sample itself.
        meta = study_meta.get(w.study_id or "", {})
        rows.append([
            w.sample_id or "",
            w.sample_alias or "",
            w.sample_description or "",
            w.material or "",
            meta.get("species", ""),
            meta.get("sample_attributes", ""),
            globals_.get("cell_extr_volume", ""),
            globals_.get("user_category", ""),
            globals_.get("contact", ""),
            globals_.get("org_info", ""),
        ])
    return rows


def export_sample_lists_zip(
    plates: List[Plate],
    study_meta: Dict[str, Dict[str, str]],
    globals_: Dict[str, str],
) -> bytes:
    """One Biocrates 'Sample List' CSV per plate (samples only, no calibrator/QC/empty
    rows), bundled into a single zip archive for download."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for plate in plates:
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow(SAMPLE_LIST_COLUMNS)
            writer.writerows(_plate_rows(plate, study_meta, globals_))
            zf.writestr(f"plate_{plate.plate_number}_sample_list.csv", csv_buf.getvalue())
    return buf.getvalue()
