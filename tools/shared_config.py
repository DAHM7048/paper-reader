#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "api": {
        "api_key": "",
        "endpoint_mode": "coding-plan",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
    },
    "translate": {
        "pdf2zh_exe": "D:/study/python3.12/Scripts/pdf2zh.exe",
        "service": "zhipu",
        "model": "GLM-4-Flash-250414",
        "threads": 5,
        "timeout": 3600,
    },
    "index": {
        "model": "GLM-4-Flash-250414",
        "timeout": 900,
        "max_chunk_pages": 5,
    },
}


def merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_config_path(repo_root: Path | None = None) -> Path:
    root = repo_root or get_repo_root()
    return root / "paper_reader_config.json"


def get_local_config_path(repo_root: Path | None = None) -> Path:
    root = repo_root or get_repo_root()
    return root / "paper_reader_config.local.json"


def load_config(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or get_repo_root()
    merged = DEFAULT_CONFIG

    config_path = get_config_path(root)
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        merged = merge_dict(merged, loaded)

    local_config_path = get_local_config_path(root)
    if local_config_path.exists():
        loaded_local = json.loads(local_config_path.read_text(encoding="utf-8"))
        merged = merge_dict(merged, loaded_local)

    return merged
