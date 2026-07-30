from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import schema


class PageOutputError(ValueError):
    pass


class PageAssetMissingError(PageOutputError):
    pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset_payload(database_path: Path, asset_row) -> dict:
    try:
        asset_path = schema.resolve_asset_path(database_path, asset_row["asset_path"])
    except ValueError as exc:
        raise PageOutputError(str(exc)) from exc
    resolved_path = asset_path.resolve()
    if not asset_path.is_file():
        raise PageAssetMissingError(f"missing asset file: {asset_row['asset_path']}")
    if _file_sha256(asset_path) != asset_row["sha256"]:
        raise PageAssetMissingError(f"asset hash mismatch: {asset_row['asset_path']}")
    try:
        bbox = json.loads(asset_row["bbox_json"]) if asset_row["bbox_json"] else None
    except ValueError as exc:
        raise PageOutputError(f"invalid asset bbox json: {asset_row['asset_path']}") from exc
    return {
        "asset_path": asset_row["asset_path"],
        "resolved_path": str(resolved_path),
        "asset_type": asset_row["asset_type"],
        "sha256": asset_row["sha256"],
        "width": asset_row["width"],
        "height": asset_row["height"],
        "label": asset_row["label"],
        "caption": asset_row["caption"],
        "nearby_text": asset_row["nearby_text"],
        "bbox": bbox,
    }


def page_assets_for(conn, database_path: Path, source_pk: int, physical_page: int) -> tuple[dict | None, list[dict]]:
    rows = conn.execute(
        "SELECT * FROM assets WHERE source_pk = ? AND physical_page = ? ORDER BY asset_type, asset_path",
        (source_pk, physical_page),
    ).fetchall()
    page_render = None
    figure_crops: list[dict] = []
    for row in rows:
        payload = _asset_payload(database_path, row)
        if row["asset_type"] == "page-render" and page_render is None:
            page_render = payload
        elif row["asset_type"] == "figure-crop":
            figure_crops.append(payload)
    return page_render, figure_crops


def page_json_payload(conn, database_path: Path, source_row, page_row) -> dict:
    page_render, figure_crops = page_assets_for(conn, database_path, source_row["source_pk"], page_row["physical_page"])
    return {
        "source_path": source_row["path"],
        "physical_page": page_row["physical_page"],
        "text": page_row["text"],
        "printed_label": page_row["printed_label"],
        "extraction_method": page_row["extraction_method"],
        "extraction_status": page_row["extraction_status"],
        "pdf_link": f"{source_row['path']}#page={page_row['physical_page']}",
        "page_render": page_render,
        "figure_crops": figure_crops,
    }


def enrich_search_result_with_page_assets(conn, database_path: Path, source_row, result: dict) -> dict:
    physical_page = result.get("physical_page")
    if source_row is None or physical_page is None:
        result["page_render"] = None
        result["figure_crops"] = []
        return result
    page_render, figure_crops = page_assets_for(conn, database_path, source_row["source_pk"], physical_page)
    result["page_render"] = page_render
    result["figure_crops"] = figure_crops
    return result
