#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade Set Status v1.0 — Uppercut VFX Pipeline
Writes the Flame color label onto Shade Approval Status.
"""

import traceback
import flame
from lib.shade_api import (
    validate_config,
    get_or_create_drive,
    get_project_token,
    find_asset_for_clip,
    set_approval_status,
)

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Set Status"
VERSION = "v1.0"

# Flame colour label -> Shade Approval Status option
FLAME_TO_SHADE = {
    "Approved": "Approved",
    "Needs Review": "In Review",
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


def colour_label(item):
    raw = getattr(item, "colour_label", None)
    if hasattr(raw, "get_value"):
        try:
            raw = raw.get_value()
        except Exception:
            pass
    return str(raw).strip("'\"") if raw is not None else ""


def shade_set_status(selection):
    print(f"\n[{SCRIPT_NAME}] {VERSION} — Start")
    try:
        if not selection:
            show_message("Please select one or more clips or sequences first.")
            return

        cfg = validate_config()
        api_key = cfg.get("shade_api_key") or cfg.get("api_key")
        project_token = get_project_token(cfg, flame.projects.current_project)
        drive_id = get_or_create_drive(cfg, project_token)
        log(f"Setting Approval Status for project '{project_token}'")

        for item in selection:
            name = clip_name(item)
            if not name:
                continue
            label = colour_label(item)
            option = FLAME_TO_SHADE.get(label)
            if not option:
                if label == "In Progress":
                    msg = (
                        f"{name}: 'In Progress' has no Shade Approval Status option. "
                        "Shade has Approved, In Review, and Rejected."
                    )
                else:
                    msg = (
                        f"{name} does not have a color label that matches Shade "
                        "(Approved or Needs Review)."
                    )
                log(msg)
                flame.messages.show_in_console(msg, "info", 4)
                continue

            asset = find_asset_for_clip(api_key, drive_id, name)
            if not asset:
                msg = f"Can't find {name} in Shade."
                log(msg)
                flame.messages.show_in_console(msg, "info", 6)
                continue

            set_approval_status(api_key, drive_id, asset["id"], option)
            log(f"Set {name} to '{option}'.")

        log("Done.")
    except Exception as e:
        log(f"Failed: {e}\n{traceback.format_exc()}")
        show_message(f"Shade Set Status Error: {e}")


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
                    "execute": shade_set_status,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
