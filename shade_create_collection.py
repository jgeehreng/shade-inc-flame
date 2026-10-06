#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade Create Collection Link v1.0 — Uppercut VFX Pipeline

Builds one published collection for the selection.
Assets already in Shade are added directly.
Assets that are missing are exported (H.264), uploaded to /CONFORMS, then added.
The public URL is https://app.shade.inc/collection/{invite_id}.
"""

import datetime
import os
import secrets
import shutil
import tempfile
import time
import traceback
import flame
from PySide6 import QtWidgets, QtCore
from lib.shade_api import (
    validate_config,
    get_or_create_drive,
    get_project_token,
    find_asset_for_clip,
    _get_asset_by_path,
    upload_to_shade,
    create_collection,
    delete_collection,
    add_assets_to_collection,
    publish_collection,
)

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Create Collection Link"
VERSION = "v1.0"


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}")


def show_message(text, title=SCRIPT_NAME):
    try:
        if hasattr(flame, "message_dialog"):
            flame.message_dialog(title, text)
        else:
            QtWidgets.QMessageBox.information(None, title, text)
    except Exception:
        print(f"[{SCRIPT_NAME}] {text}")


def clip_name(item):
    try:
        return str(item.name)[1:-1].strip()
    except Exception:
        return ""


class ShadeCollectionOptionsDialog(QtWidgets.QDialog):
    def __init__(self, default_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shade Collection Link")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(640)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.name_edit = QtWidgets.QLineEdit(default_name)
        form.addRow("Collection Name:", self.name_edit)

        pw_row = QtWidgets.QHBoxLayout()
        self.pw_enabled = QtWidgets.QCheckBox("Enable")
        self.pw_edit = QtWidgets.QLineEdit()
        self.pw_edit.setPlaceholderText("Password")
        self.pw_edit.setEnabled(False)
        gen_btn = QtWidgets.QPushButton("Generate")
        gen_btn.setFixedWidth(80)
        gen_btn.setEnabled(False)
        gen_btn.clicked.connect(self._generate_password)
        self.pw_enabled.toggled.connect(self.pw_edit.setEnabled)
        self.pw_enabled.toggled.connect(gen_btn.setEnabled)
        pw_row.addWidget(self.pw_enabled)
        pw_row.addWidget(self.pw_edit)
        pw_row.addWidget(gen_btn)
        form.addRow("Password:", pw_row)
        self._generate_password()

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QtWidgets.QPushButton("Create Collection")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

    def _generate_password(self):
        self.pw_edit.setText(secrets.token_urlsafe(9))

    def _on_accept(self):
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Validation", "Collection name cannot be empty.")
            return
        if self.pw_enabled.isChecked() and not self.pw_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Validation", "Enter a password or disable Password.")
            return
        self.accept()

    def collection_name(self):
        return self.name_edit.text().strip()

    def password(self):
        if self.pw_enabled.isChecked():
            return self.pw_edit.text().strip()
        return ""


class ShadeCollectionResultsDialog(QtWidgets.QDialog):
    def __init__(self, share_url, password="", collection_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shade Collection Link Created")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(640)

        layout = QtWidgets.QVBoxLayout(self)
        if collection_name:
            title = QtWidgets.QLabel(f"<b>{collection_name}</b> is ready to send.")
            title.setTextFormat(QtCore.Qt.RichText)
            layout.addWidget(title)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        url_row = QtWidgets.QHBoxLayout()
        self.url_edit = QtWidgets.QLineEdit(share_url)
        self.url_edit.setReadOnly(True)
        copy_url = QtWidgets.QPushButton("Copy")
        copy_url.setFixedWidth(60)
        copy_url.clicked.connect(lambda: self._copy(self.url_edit.text(), copy_url))
        url_row.addWidget(self.url_edit)
        url_row.addWidget(copy_url)
        form.addRow("Collection URL:", url_row)

        pw_row = QtWidgets.QHBoxLayout()
        self.pw_edit = QtWidgets.QLineEdit(password or "(no password set)")
        self.pw_edit.setReadOnly(True)
        copy_pw = QtWidgets.QPushButton("Copy")
        copy_pw.setFixedWidth(60)
        copy_pw.setEnabled(bool(password))
        copy_pw.clicked.connect(lambda: self._copy(password, copy_pw))
        pw_row.addWidget(self.pw_edit)
        pw_row.addWidget(copy_pw)
        form.addRow("Password:", pw_row)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        copy_both = QtWidgets.QPushButton("Copy Both to Clipboard")
        copy_both.clicked.connect(lambda: self._copy_both(share_url, password, copy_both))
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(copy_both)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    @staticmethod
    def _copy(text, button):
        QtWidgets.QApplication.clipboard().setText(text)
        original = button.text()
        button.setText("Copied!")
        QtCore.QTimer.singleShot(1500, lambda: button.setText(original))

    @staticmethod
    def _copy_both(url, password, button):
        parts = [f"Collection: {url}"]
        if password:
            parts.append(f"Password: {password}")
        QtWidgets.QApplication.clipboard().setText("\n".join(parts))
        original = button.text()
        button.setText("Copied!")
        QtCore.QTimer.singleShot(1500, lambda: button.setText(original))


def classify_selection(selection):
    entries = []
    for item in selection:
        if isinstance(item, flame.PySegment):
            try:
                sequence_obj = item.parent.parent.parent
            except Exception:
                log(f"Skipping segment with no parent sequence: {item}")
                continue
            name = clip_name(sequence_obj)
            target = sequence_obj
        elif isinstance(item, (flame.PyClip, flame.PySequence)):
            name = clip_name(item)
            target = item
        else:
            log(f"Skipping unsupported selection item: {item}")
            continue
        if name:
            entries.append({"name": name, "export_target": target})

    unique = {}
    for entry in entries:
        unique.setdefault(entry["name"], entry)
    return list(unique.values())


def export_item(item, export_dir, preset_path):
    before = set(os.listdir(export_dir))
    exporter = flame.PyExporter()
    exporter.foreground = True
    exporter.export_between_marks = False
    exporter.use_top_video_track = True
    exporter.export(item, preset_path, export_dir)
    new_files = sorted(
        os.path.join(export_dir, name)
        for name in (set(os.listdir(export_dir)) - before)
        if os.path.isfile(os.path.join(export_dir, name))
    )
    if not new_files:
        raise RuntimeError("Export produced no file.")
    return new_files[0]


def resolve_asset(api_key, drive_id, name, dest_path=None, attempts=6):
    """Find an asset by name, falling back to the upload path while Shade indexes it."""
    last_error = None
    for attempt in range(attempts):
        asset = find_asset_for_clip(api_key, drive_id, name)
        if asset and asset.get("id"):
            return asset
        if dest_path:
            try:
                asset = _get_asset_by_path(api_key, drive_id, dest_path)
                if asset and asset.get("id"):
                    return asset
            except Exception as e:
                last_error = e
        if attempt + 1 < attempts:
            time.sleep(2)
    if last_error:
        log(f"Asset lookup for '{name}' failed: {last_error}")
    return None


def create_collection_link(selection):
    print(f"\n[{SCRIPT_NAME}] {VERSION} — Start")
    collection_id = None
    api_key = None
    drive_id = None
    try:
        if not selection:
            show_message("Please select one or more clips, sequences, or segments first.")
            return

        cfg = validate_config()
        api_key = cfg.get("shade_api_key") or cfg.get("api_key")
        project = flame.projects.current_project
        project_token = get_project_token(cfg, project)
        drive_id = get_or_create_drive(cfg, project_token)

        entries = classify_selection(selection)
        if not entries:
            show_message("No supported clips, sequences, or segments were selected.")
            return

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        if len(entries) == 1:
            default_name = f"{entries[0]['name']} — {date_str}"
        else:
            default_name = f"{project_token} Review ({len(entries)} items) — {date_str}"

        options = ShadeCollectionOptionsDialog(default_name=default_name)
        if options.exec() != QtWidgets.QDialog.Accepted:
            log("Collection link creation cancelled.")
            return

        collection_name = options.collection_name()
        password = options.password()

        asset_ids = []
        included = []
        missing = []
        for entry in entries:
            asset = find_asset_for_clip(api_key, drive_id, entry["name"])
            if asset and asset.get("id"):
                asset_ids.append(asset["id"])
                included.append(entry["name"])
                log(f"Using existing Shade asset '{entry['name']}'")
            else:
                missing.append(entry)

        if missing:
            preset_path = cfg.get("preset_path_h264")
            if not preset_path or not os.path.exists(preset_path):
                raise RuntimeError(f"Missing export preset: {preset_path}")
            export_dir = tempfile.mkdtemp(prefix=f"shade_collection_{now.strftime('%H%M%S')}_")
            log(f"Staging export in {export_dir}")
            try:
                for entry in missing:
                    try:
                        local_path = export_item(entry["export_target"], export_dir, preset_path)
                        filename = os.path.basename(local_path)
                        dest_path = f"/CONFORMS/{filename}"
                        upload_to_shade(
                            local_path,
                            project_token,
                            auto_stack=False,
                            dest_path=dest_path,
                        )
                        asset = resolve_asset(api_key, drive_id, entry["name"], dest_path=dest_path)
                        if not asset or not asset.get("id"):
                            raise RuntimeError("Upload finished, but Shade has not indexed the asset yet.")
                        asset_ids.append(asset["id"])
                        included.append(entry["name"])
                        log(f"Exported and uploaded '{entry['name']}'")
                    except Exception as e:
                        log(f"Export/upload failed for '{entry['name']}': {e}")
            finally:
                if len(included) >= len(entries):
                    shutil.rmtree(export_dir, ignore_errors=True)
                else:
                    log(f"Left staging export at {export_dir}")

        if not asset_ids:
            show_message("No assets could be found or uploaded for a collection.")
            return

        collection_id = create_collection(api_key, drive_id, collection_name)
        add_assets_to_collection(api_key, drive_id, collection_id, asset_ids)
        collection = publish_collection(
            api_key,
            drive_id,
            collection_id,
            password=password or None,
        )
        url = collection.get("url")
        if not url:
            raise RuntimeError("Shade did not return a collection link.")

        try:
            QtWidgets.QApplication.clipboard().setText(url)
        except Exception as e:
            log(f"Could not copy URL to clipboard: {e}")

        log(f"Collection link created: {url}")
        log(f"Items: {', '.join(included)}")
        collection_id = None
        ShadeCollectionResultsDialog(
            share_url=url,
            password=password,
            collection_name=collection_name,
        ).exec()
    except Exception as e:
        log(f"Failed: {e}\n{traceback.format_exc()}")
        if collection_id and api_key and drive_id:
            try:
                delete_collection(api_key, drive_id, collection_id)
            except Exception as cleanup_error:
                log(f"Could not remove unfinished collection {collection_id}: {cleanup_error}")
        show_message(f"Shade Create Collection Error: {e}")

    print(f"[{SCRIPT_NAME}] Done.")


def scope_collection(selection):
    return any(isinstance(item, (flame.PyClip, flame.PySequence, flame.PySegment)) for item in selection)


def get_media_panel_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "order": 3,
                    "isVisible": scope_collection,
                    "execute": create_collection_link,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
