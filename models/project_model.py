# -*- coding: utf-8 -*-
import os
import json
from pathlib import Path

class ProjectModel:
    """Manages the metadata for a single project (metadata.json)."""
    
    METADATA_FILE_NAME = "metadata.json"
    
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.metadata_path = self.project_dir / self.METADATA_FILE_NAME
        
        # Default empty fields
        self.project_id = self.project_dir.name
        self.index = 0
        self.col1_name = ""
        self.col7_notes = ""
        self.google_drive_url = ""
        self.chinese_text = ""
        self.spanish_text = ""
        self.spanish_segments = []  # List of dict: {"text": str, "length": int, "duration": int}
        self.associated_media = []  # List of dict: {"file_path": str, "associated_text_segment_index": int/None}
        self.prompt_template = ""
        self.selected_template_id = ""
        self.selected_motion_id = ""
        self.enable_end_frame = None  # None: follow config, True/False: explicit project override
        
        # Load existing metadata if available
        self.load()

    def load(self):
        """Loads metadata from project_dir/metadata.json."""
        if self.metadata_path.exists():
            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.project_id = data.get("project_id", self.project_id)
                    self.index = data.get("index", self.index)
                    self.col1_name = data.get("col1_name", self.col1_name)
                    self.col7_notes = data.get("col7_notes", self.col7_notes)
                    self.google_drive_url = data.get("google_drive_url", self.google_drive_url)
                    self.chinese_text = data.get("chinese_text", self.chinese_text)
                    self.spanish_text = data.get("spanish_text", self.spanish_text)
                    self.spanish_segments = data.get("spanish_segments", self.spanish_segments)
                    self.associated_media = data.get("associated_media", self.associated_media)
                    self.prompt_template = data.get("prompt_template", self.prompt_template)
                    self.selected_template_id = data.get("selected_template_id", "")
                    self.selected_motion_id = data.get("selected_motion_id", "")
                    self.enable_end_frame = data.get("enable_end_frame", None)
                
                # Proactively ensure subtitle file exists
                subtitles_dir = self.project_dir.parent / "字幕"
                subtitle_file_path = subtitles_dir / f"{self.project_id}.txt"
                if not subtitle_file_path.exists() and self.spanish_segments:
                    self.save_subtitle_file()
            except Exception as e:
                print(f"Error loading project metadata: {e}")

    def save(self):
        """Saves current state to project_dir/metadata.json."""
        data = {
            "project_id": self.project_id,
            "index": self.index,
            "col1_name": self.col1_name,
            "col7_notes": self.col7_notes,
            "google_drive_url": self.google_drive_url,
            "chinese_text": self.chinese_text,
            "spanish_text": self.spanish_text,
            "spanish_segments": self.spanish_segments,
            "associated_media": self.associated_media,
            "prompt_template": self.prompt_template,
            "selected_template_id": self.selected_template_id,
            "selected_motion_id": self.selected_motion_id
        }
        if self.enable_end_frame is not None:
            data["enable_end_frame"] = self.enable_end_frame
        try:
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # Save subtitle file
            self.save_subtitle_file()
            
            return True
        except Exception as e:
            print(f"Error saving project metadata: {e}")
            return False

    def save_subtitle_file(self):
        """Saves Spanish segments as a subtitle text file in the '字幕' directory under the base storage path."""
        try:
            subtitles_dir = self.project_dir.parent / "字幕"
            subtitles_dir.mkdir(parents=True, exist_ok=True)
            
            subtitle_file_path = subtitles_dir / f"{self.project_id}.txt"
            
            lines = []
            for seg in self.spanish_segments:
                text = seg.get("text", "").strip()
                if text:
                    # Split this segment's text into short lines (max 28 characters)
                    short_lines = self.split_text_into_short_lines(text, max_len=28)
                    lines.extend(short_lines)
                    
            with open(subtitle_file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                
            return True
        except Exception as e:
            print(f"Error saving subtitle file: {e}")
            return False

    def split_text_into_short_lines(self, text, max_len=28):
        """Splits a string of text into lines of at most max_len characters, breaking at spaces."""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if not current_line:
                current_line = word
            else:
                if len(current_line) + 1 + len(word) <= max_len:
                    current_line += " " + word
                else:
                    lines.append(current_line)
                    current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def update_media_files(self):
        """Scans project_dir/downloads and updates associated_media, ensuring unique stems across all files."""
        downloads_dir = self.project_dir / "downloads"
        if not downloads_dir.exists():
            return
            
        from services.downloader import ensure_unique_stems_in_dir
        rename_map = ensure_unique_stems_in_dir(downloads_dir)
        if rename_map:
            for seg in self.spanish_segments:
                if isinstance(seg, dict):
                    if seg.get("image_name") in rename_map:
                        seg["image_name"] = rename_map[seg["image_name"]]
                    if seg.get("end_image_name") in rename_map:
                        seg["end_image_name"] = rename_map[seg["end_image_name"]]

        existing_paths = {item["file_path"] for item in self.associated_media}
        new_media = list(self.associated_media)
        
        # Scan downloads folder
        for item in downloads_dir.iterdir():
            if item.is_file():
                # We save relative path to project_dir
                rel_path = f"downloads/{item.name}"
                if rel_path not in existing_paths:
                    new_media.append({
                        "file_path": rel_path,
                        "associated_text_segment_index": None
                    })
                    
        # Remove deleted files from metadata
        final_media = []
        for media in new_media:
            full_path = self.project_dir / media["file_path"]
            if full_path.exists():
                final_media.append(media)
                
        self.associated_media = final_media
        self.save()
