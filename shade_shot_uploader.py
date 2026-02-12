#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shade Shot Uploader — Uppercut VFX Pipeline
- export selection into FROM_FLAME/date/time
- upload shots to Shade
- auto-version-up in Flame before export
- auto-stack enabled
"""

import flame
import datetime
import os
import re
import traceback
from PySide6 import QtWidgets, QtCore
import lib.shade_api as shade_api

FOLDER_NAME = "UC Shade"
SCRIPT_NAME = "Shot Uploader"
VERSION = "v1.0.0"


# ----------------------------------------------------------
# Toast
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


# ----------------------------------------------------------
# Logging
# ----------------------------------------------------------
def log(msg):
    print(f"[{SCRIPT_NAME}] {msg}")


def attr(x):
    try:
        return x.get_value() if hasattr(x, "get_value") else x
    except Exception:
        return x


# ----------------------------------------------------------
# Progress UI
# ----------------------------------------------------------
class ShadeShotProgress(QtWidgets.QDialog):
    def __init__(self, total_files):
        super().__init__()
        self.setWindowTitle("Shade Shot Upload Progress")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)
        self.layout = QtWidgets.QVBoxLayout(self)

        self.label = QtWidgets.QLabel("Preparing upload.")
        self.file_progress = QtWidgets.QProgressBar()
        self.total_progress = QtWidgets.QProgressBar()
        self.total_progress.setRange(0, total_files)

        self.layout.addWidget(self.label)
        self.layout.addWidget(QtWidgets.QLabel("File Progress:"))
        self.layout.addWidget(self.file_progress)
        self.layout.addWidget(QtWidgets.QLabel("Overall Progress:"))
        self.layout.addWidget(self.total_progress)
        self.resize(440, 160)

    def update_file_percent(self, percent, message):
        self.label.setText(message)
        self.file_progress.setValue(percent)
        QtWidgets.QApplication.processEvents()

    def update_total_file(self, idx, total, filename):
        self.total_progress.setValue(idx - 1)
        self.file_progress.setValue(0)
        self.label.setText(f"Uploading {os.path.basename(filename)} ({idx}/{total}).")
        QtWidgets.QApplication.processEvents()

    def finish(self):
        self.total_progress.setValue(self.total_progress.maximum())
        self.file_progress.setValue(100)
        self.label.setText("All uploads complete!")
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(1500, self.accept)


# ----------------------------------------------------------
# Shared Library Helpers
# ----------------------------------------------------------
def get_or_create_shared_library(name="FROM_FLAME"):
    project = flame.projects.current_project
    for lib in project.shared_libraries:
        if attr(lib.name).strip().lower() == name.lower():
            return lib
    new_lib = project.create_shared_library(name)
    if not new_lib:
        raise RuntimeError(f"Failed to create Shared Library '{name}'.")
    return new_lib


def ensure_folder(parent, name):
    for f in parent.folders:
        if attr(f.name) == name:
            return f
    if hasattr(parent, "create_folder"):
        return parent.create_folder(name)
    raise RuntimeError("Flame version does not expose create_folder().")


# ----------------------------------------------------------
# Auto version-up (Option A: exact-name search against Shade)
# ----------------------------------------------------------
def auto_version_up_flame(selection, cfg, project_token):
    """
    For each clip in selection:
    - use full clip name (e.g., 'shot_v01')
    - search Shade for exact name (extension stripped)
    - if found, bump to next version locally before export
    """
    try:
        api_key = cfg.get("shade_api_key") or cfg.get("api_key")
        drive_id = shade_api.get_or_create_drive(cfg, project_token)

        for item in selection:
            raw_name = str(item.name)[1:-1]
            clip_name = raw_name.strip()
            log(f"[auto_version_up_flame] Checking '{clip_name}'")

            m = re.search(r"([vV])(\d+)$", clip_name)
            if not m:
                log(f"[auto_version_up_flame] Name '{clip_name}' does not end with a version tag like 'v01'. Skipping.")
                continue

            prefix = m.group(1)
            current_version = int(m.group(2))
            base_no_version = clip_name[:m.start()]

            try:
                results = shade_api.search_shade_assets(api_key, drive_id, base_no_version, limit=50)
            except Exception as e:
                log(f"[auto_version_up_flame] Shade search failed for '{clip_name}': {e}")
                continue

            max_found = current_version
            pattern = re.compile(rf"^{re.escape(base_no_version)}[vV](\d+)$")
            for r in results:
                shade_name = r.get("name", "")
                no_ext = os.path.splitext(shade_name)[0]
                mver = pattern.match(no_ext)
                if mver:
                    try:
                        ver_num = int(mver.group(1))
                        if ver_num > max_found:
                            max_found = ver_num
                    except Exception:
                        pass

            if max_found == current_version:
                log(f"No higher version found in Shade for '{base_no_version}'. Keeping name.")
                continue

            next_version = max_found + 1
            new_name = f"{base_no_version}{prefix}{next_version:02d}"

            try:
                if hasattr(item, "name") and hasattr(item.name, "set_value"):
                    item.name.set_value(new_name)
                else:
                    item.name = new_name
                log(f"Renamed '{clip_name}' to '{new_name}'.")
            except Exception as e:
                log(f"Could not rename '{clip_name}': {e}")

    except Exception as e:
        log(f"Version check skipped due to error: {e}")


# ----------------------------------------------------------
# Export and collect
# ----------------------------------------------------------
def export_and_collect(selection, project_token, jobs_folder, cfg):
    lib = get_or_create_shared_library("FROM_FLAME")
    lib.acquire_exclusive_access()
    try:
        date_name = datetime.datetime.now().strftime("%Y-%m-%d")
        time_name = datetime.datetime.now().strftime("%H%M")

        date_folder = ensure_folder(lib, date_name)
        time_folder = ensure_folder(date_folder, time_name)

        auto_version_up_flame(selection, cfg, project_token)

        log("Copying selection into Shared Library folder.")
        if flame.get_current_tab() == "MediaHub":
            flame.set_current_tab("Timeline")
        for item in selection:
            try:
                flame.media_panel.copy(item, time_folder)
            except Exception as e:
                log(f"Failed to copy {getattr(item, 'name', 'item')}: {e}")
        log("Selection copied.")

        posting_folder = os.path.join(
            jobs_folder,
            project_token,
            "FROM_FLAME",
            date_name,
        )
        os.makedirs(posting_folder, exist_ok=True)
        log(f"Posting folder: {posting_folder}")

        preset_path = cfg.get("preset_path_h264")
        if not preset_path or not os.path.exists(preset_path):
            raise RuntimeError(f"Missing preset: {preset_path}")

        exporter = flame.PyExporter()
        exporter.foreground = True
        exporter.export_between_marks = True
        exporter.use_top_video_track = True
        exporter.export(time_folder, preset_path, posting_folder)
        log("Export complete.")

        return os.path.join(posting_folder, time_name)
    finally:
        lib.release_exclusive_access()


# ----------------------------------------------------------
# Main upload
# ----------------------------------------------------------
def start_upload(selection):
    print(f"\n[{SCRIPT_NAME}] {VERSION} — Start")
    try:
        cfg = shade_api.validate_config()
        project = flame.projects.current_project

        token_mode = cfg.get("project_token", "nickname")
        project_token = (
            attr(project.nickname)
            if token_mode == "nickname"
            else attr(project.name)
        )

        jobs_folder = cfg.get("jobs_folder", "/Volumes/vfx/UC_Jobs")

        reply = QtWidgets.QMessageBox.question(
            None,
            "Confirm Upload",
            f"Upload shots for project '{project_token}' to Shade?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            log("Upload canceled.")
            return

        posting_folder = export_and_collect(selection, project_token, jobs_folder, cfg)

        files = [
            os.path.join(root, f)
            for root, _, fnames in os.walk(posting_folder)
            for f in fnames
        ]
        if not files:
            raise RuntimeError("No files exported for upload.")

        progress = ShadeShotProgress(len(files))
        progress.show()

        drive_id = shade_api.get_or_create_drive(cfg, project_token)
        if not drive_id:
            msg = f"Could not find or create Shade drive for '{project_token}'. Upload aborted."
            log(msg)
            show_toast(msg, 5)
            return

        for idx, local_path in enumerate(files, 1):
            progress.update_total_file(idx, len(files), local_path)
            try:
                filename = os.path.basename(local_path)
                dest_path = f"/TEST/{filename}"

                shade_api.upload_to_shade(
                    local_path,
                    project_token,
                    progress_callback=progress.update_file_percent,
                    auto_stack=True,
                    dest_path=dest_path,
                )
            except Exception as e:
                log(f"Failed to upload {local_path}: {e}")
                show_toast(f"Upload failed for {os.path.basename(local_path)}", 5)

        progress.finish()
        show_toast("Shade Shot upload complete.", 5)
        log("All uploads complete.")
    except Exception as e:
        log(f"Fatal error: {e}\n{traceback.format_exc()}")
        show_toast(f"Shade Shot Uploader Error: {e}", 5)

    print(f"[{SCRIPT_NAME}] Done.")


# ----------------------------------------------------------
# Menu
# ----------------------------------------------------------
def scope_clip(selection):
    return all(isinstance(item, flame.PyClip) for item in selection)


def get_media_panel_custom_ui_actions():
    return [
        {
            "name": FOLDER_NAME,
            "actions": [
                {
                    "name": SCRIPT_NAME,
                    "isVisible": scope_clip,
                    "execute": start_upload,
                    "minimumVersion": "2025",
                }
            ],
        }
    ]
