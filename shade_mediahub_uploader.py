#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade MediaHub Uploader — Uppercut VFX Pipeline

Uploads files selected in Flame’s MediaHub to Shade.
- respects current Shade config (global + user)
- uses project token (nickname or name, from config)
- does NOT flatten: we just walk the selection and upload each file we can resolve
- progress dialog + toast-style fallback
"""

import flame
import os
import traceback
from PySide6 import QtWidgets, QtCore

import lib.shade_api as shade_api  # uses your latest working shade_api

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Uploader to Shade"
VERSION = "v1.3.1"


# ----------------------------------------------------------
# Toast / logging
# ----------------------------------------------------------
def show_toast(message, duration=5, title=SCRIPT_NAME):
    try:
        if hasattr(flame, "display_toast"):
            flame.display_toast(message, duration)
            return
    except Exception:
        pass

    print(f"[{title}] {message}")
    msg_box = QtWidgets.QMessageBox()
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.setIcon(QtWidgets.QMessageBox.Information)
    QtCore.QTimer.singleShot(duration * 1000, msg_box.accept)
    msg_box.exec_()


def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}")


# ----------------------------------------------------------
# Progress UI
# ----------------------------------------------------------
class ShadeMediaHubProgress(QtWidgets.QDialog):
    def __init__(self, total_files: int):
        super().__init__()
        self.setWindowTitle("Shade MediaHub Upload")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.layout = QtWidgets.QVBoxLayout(self)

        self.label = QtWidgets.QLabel("Preparing upload.")
        self.file_progress = QtWidgets.QProgressBar()
        self.total_progress = QtWidgets.QProgressBar()
        self.total_progress.setRange(0, max(total_files, 1))

        self.layout.addWidget(self.label)
        self.layout.addWidget(QtWidgets.QLabel("File Progress:"))
        self.layout.addWidget(self.file_progress)
        self.layout.addWidget(QtWidgets.QLabel("Overall Progress:"))
        self.layout.addWidget(self.total_progress)
        self.resize(420, 150)

    def update_file_percent(self, percent, message):
        self.label.setText(message)
        self.file_progress.setValue(percent)
        QtWidgets.QApplication.processEvents()

    def update_total(self, idx, total, path):
        self.total_progress.setValue(idx - 1)
        self.file_progress.setValue(0)
        base = os.path.basename(path) if path else ""
        self.label.setText(f"Uploading {base} ({idx}/{total}).")
        QtWidgets.QApplication.processEvents()

    def finish(self):
        self.total_progress.setValue(self.total_progress.maximum())
        self.file_progress.setValue(100)
        self.label.setText("All uploads complete!")
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(1500, self.accept)


# ----------------------------------------------------------
# MediaHub item -> file(s)
# ----------------------------------------------------------
def _collect_paths_from_mediahub_item(item, out_list):
    """
    Try to resolve a MediaHub selection item to filesystem paths.
    Supports files *and* folders now.
    """
    # 1) Direct file
    for attr_name in ("file_path", "path", "source_path"):
        if hasattr(item, attr_name):
            p = getattr(item, attr_name)
            if p and isinstance(p, str):
                if os.path.isfile(p):
                    out_list.append(p)
                    return
                elif os.path.isdir(p):
                    for root, _, files in os.walk(p):
                        for f in files:
                            full_path = os.path.join(root, f)
                            out_list.append(full_path)
                    return

    # 2) Children (Flame MediaHub nested objects)
    for attr_name in ("children", "get_children"):
        if hasattr(item, attr_name):
            try:
                kids = getattr(item, attr_name)
                if callable(kids):
                    kids = kids()
                for child in kids:
                    _collect_paths_from_mediahub_item(child, out_list)
                return
            except Exception:
                pass

    # 3) Fallback
    name = getattr(item, "name", str(item))
    log(f"Skipping MediaHub item (no path): {name}")

def collect_paths_from_selection(selection):
    files = []
    for item in selection:
        _collect_paths_from_mediahub_item(item, files)
    # de-dup, maintain order
    seen = set()
    unique_files = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return unique_files


# ----------------------------------------------------------
# Main upload
# ----------------------------------------------------------
def start_mediahub_upload(selection):
    print(f"\n[{SCRIPT_NAME}] {VERSION} — Start")
    try:
        if not selection:
            show_toast("Please select one or more items in MediaHub.", 5)
            return

        # load Shade config
        cfg = shade_api.validate_config()
        project = flame.projects.current_project

        # project token from config (nickname default)
        token_mode = cfg.get("project_token", "nickname")
        project_token = (
            str(project.nickname) if token_mode == "nickname" else str(project.name)
        )

        # collect real file paths from MediaHub selection
        files = collect_paths_from_selection(selection)
        if not files:
            show_toast("No file-based items found in selection.", 5)
            return

        log(f"Found {len(files)} file(s) to upload for project token '{project_token}'")

        # confirm
        reply = QtWidgets.QMessageBox.question(
            None,
            "Upload to Shade",
            f"Upload {len(files)} file(s) to Shade drive for '{project_token}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            log("Upload canceled.")
            return

        # progress dialog
        progress = ShadeMediaHubProgress(len(files))
        progress.show()

        # ensure drive exists up front
        drive_id = shade_api.get_or_create_drive(cfg, project_token)
        if not drive_id:
            show_toast(f"Could not find/create Shade drive for '{project_token}'", 5)
            return

        # Determine a base folder so we can keep relative structure
        # (if user selected multiple roots, pick their common prefix)
        common_root = os.path.commonpath(files)
        if not os.path.isdir(common_root):
            common_root = os.path.dirname(common_root)
        log(f"Common root for structure preservation: {common_root}")

        uploaded_ok = 0
        for idx, local_path in enumerate(files, 1):
            progress.update_total(idx, len(files), local_path)
            try:
                rel_path = os.path.relpath(local_path, common_root)
                # ensure forward slashes for Shade paths
                rel_path = rel_path.replace(os.sep, "/")

                # Build a structured destination path under /CONFORMS
                dest_path = f"/CONFORMS/{rel_path}"
                log(f"Uploading {local_path} -> {dest_path}")

                # Call upload_to_shade with explicit dest_path
                shade_api.upload_to_shade(
                    local_path,
                    project_token,
                    dest_path=dest_path,
                    progress_callback=progress.update_file_percent,
                    auto_stack=False,
                )
                uploaded_ok += 1
            except Exception as e:
                log(f"Failed to upload {local_path}: {e}")
                show_toast(f"Upload failed: {os.path.basename(local_path)}", 3)


        progress.finish()
        show_toast(f"Uploaded {uploaded_ok}/{len(files)} file(s) to Shade.", 4)
        log("MediaHub upload complete.")

    except Exception as e:
        log(f"Fatal error: {e}\n{traceback.format_exc()}")
        show_toast(f"Shade MediaHub Uploader Error: {e}", 6)

    print(f"[{SCRIPT_NAME}] Done.")


# ----------------------------------------------------------
# Flame Menu Integration
# ----------------------------------------------------------
def scope_mediahub(selection):
    # show whenever there is *any* selection in MediaHub
    return bool(selection)

def get_mediahub_files_custom_ui_actions():
    # MediaHub context menu — supports files *and* folders
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "isVisible": scope_mediahub,
                    "execute": start_mediahub_upload,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]

# ----------------------------------------------------------
# Standalone (for testing outside Flame)
# ----------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    # no real selection here — just verify it imports
    QtWidgets.QMessageBox.information(
        None, SCRIPT_NAME, f"{SCRIPT_NAME} {VERSION} loaded."
    )
    app.exec()
