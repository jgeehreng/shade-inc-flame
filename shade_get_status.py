#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade Get Status v1.0 — Uppercut VFX Pipeline
Reads Approval Status from Shade and applies the matching Flame color label.
"""

import traceback
import flame
from lib.shade_api import (
    validate_config,
    get_or_create_drive,
    get_project_token,
    find_asset_for_clip,
    get_approval_status,
)

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Get Status"
VERSION = "v1.0"

# Shade Approval Status option -> Flame colour label
SHADE_TO_FLAME = {
    "Approved": "Approved",
    "In Review": "Needs Review",
    "Rejected": "Rejected",
}

FLAME_COLOURS = {
    "Approved": (0.11372549086809158, 0.26274511218070984, 0.1764705926179886),
    "Needs Review": (0.6000000238418579, 0.3450980484485626, 0.16470588743686676),
    "Rejected": (0.45, 0.12, 0.12),
}


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}")


def show_message(text, title=SCRIPT_NAME):
    try:
        if hasattr(flame, "message_dialog"):
            flame.message_dialog(title, text)
        else:
            from PySide6 import QtWidgets
            QtWidgets.QMessageBox.information(None, title, text)
    except Exception:
        print(f"[{SCRIPT_NAME}] {text}")


def clip_name(item):
    try:
        return str(item.name)[1:-1].strip()
    except Exception:
        return ""


def apply_colour(obj, label):
    try:
        obj.colour_label = label
        return
    except Exception:
        pass
    colour = FLAME_COLOURS.get(label)
    if colour is not None:
        obj.colour = colour


def shade_get_status(selection):
    print(f"\n[{SCRIPT_NAME}] {VERSION} — Start")
    try:
        if not selection:
            show_message("Please select one or more clips or sequences first.")
            return

        cfg = validate_config()
        api_key = cfg.get("shade_api_key") or cfg.get("api_key")
        project_token = get_project_token(cfg, flame.projects.current_project)
        drive_id = get_or_create_drive(cfg, project_token)
        log(f"Approval Status for project '{project_token}'")

        for item in selection:
            name = clip_name(item)
            if not name:
                continue
            asset = find_asset_for_clip(api_key, drive_id, name)
            if not asset:
                msg = f"NOT FOUND in Shade: {name}"
                log(msg)
                flame.messages.show_in_console(msg, "info", 6)
                continue

            status = get_approval_status(api_key, drive_id, asset["id"])
            label = SHADE_TO_FLAME.get(status)
            if not label:
                msg = f"{name}: No mappable status ({status or 'unset'})"
                log(msg)
                flame.messages.show_in_console(msg, "info", 3)
                continue

            apply_colour(item, label)
            log(f"Applied color label for {name}: {status} -> {label}")

        log("Done.")
    except Exception as e:
        log(f"Failed: {e}\n{traceback.format_exc()}")
        show_message(f"Shade Get Status Error: {e}")


def scope_clip_or_sequence(selection):
    return any(isinstance(item, (flame.PyClip, flame.PySequence)) for item in selection)


def get_media_panel_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "order": 7,
                    "isVisible": scope_clip_or_sequence,
                    "execute": shade_get_status,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
