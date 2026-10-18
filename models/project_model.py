# -*- coding: utf-8 -*-
import os
import json
from pathlib import Path
from services.project_prompts import ProjectPromptStore

class ProjectModel:
    """Manages the metadata for a single project (metadata.json)."""
    
    METADATA_FILE_NAME = "metadata.json"
    
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.metadata_path = self.project_dir / self.METADATA_FILE_NAME
        self.prompt_store = ProjectPromptStore(self.project_dir)
        
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
                    project_id = data.get("project_id", self.project_id)
                    if (isinstance(project_id, str) and project_id not in ('', '.', '..')
                            and not any(c in project_id for c in '/\\:')
                            and not any(ord(c) < 32 for c in project_id)):
                        self.project_id = project_id
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

    def _get_global_max_image_index(self):
        """Finds the maximum numeric image filename across all projects."""
        max_idx = 0
        base_path = self.project_dir.parent
        if not base_path.exists():
            return 0
            
        import re
        pattern = re.compile(r'^(\d+)\.[a-zA-Z]+$')
        
        for proj_dir in base_path.iterdir():
            if proj_dir.is_dir():
                dl_dir = proj_dir / "downloads"
                if dl_dir.exists():
                    for f in dl_dir.iterdir():
                        if f.is_file():
                            match = pattern.match(f.name)
                            if match:
                                val = int(match.group(1))
                                if val > max_idx:
                                    max_idx = val
        return max_idx

    def rename_images(self, start_idx=None, return_next_idx=False):
        """Renames downloaded images to a global sequential format: 1.ext, 2.ext, etc."""
        downloads_dir = self.project_dir / "downloads"
        if not downloads_dir.exists():
            return (0, start_idx) if return_next_idx else 0
            
        images = []
        for item in downloads_dir.iterdir():
            if item.is_file() and item.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                images.append(item)
                
        if not images:
            return (0, start_idx) if return_next_idx else 0
            
        images.sort(key=lambda x: (x.stat().st_mtime, x.name))
        
        if start_idx is None:
            start_idx = self._get_global_max_image_index() + 1
            
        rename_count = 0
        idx = start_idx
        path_mapping = {}
        
        import uuid
        
        # Pass 1: rename to temporary names to avoid collision within the same folder
        tmp_images = []
        for img in images:
            tmp_name = f"tmp_{uuid.uuid4().hex}{img.suffix}"
            tmp_path = downloads_dir / tmp_name
            try:
                img.rename(tmp_path)
                tmp_images.append((img, tmp_path))
            except Exception as e:
                print(f"Failed to temp rename {img.name}: {e}")
                tmp_images.append((img, img))
                
        # Pass 2: rename to final numeric sequence
        for original_img, current_path in tmp_images:
            ext = original_img.suffix.lower()
            if ext == '.jpeg': ext = '.jpg'
            new_name = f"{idx}{ext}"
            new_path = downloads_dir / new_name
            
            try:
                current_path.rename(new_path)
                old_rel = f"downloads/{original_img.name}"
                new_rel = f"downloads/{new_name}"
                if original_img.name != new_name:
                    path_mapping[old_rel] = new_rel
                    rename_count += 1
            except Exception as e:
                print(f"Failed to rename {original_img.name} to {new_name}: {e}")
                
            idx += 1
            
        if rename_count > 0:
            name_mapping = {} # old_name -> new_name
            for old_rel, new_rel in path_mapping.items():
                old_name = old_rel.split('/')[-1]
                new_name = new_rel.split('/')[-1]
                name_mapping[old_name] = new_name
                
            for media in self.associated_media:
                old_p = media.get("file_path")
                if old_p in path_mapping:
                    media["file_path"] = path_mapping[old_p]
                    
            for seg in self.spanish_segments:
                if seg.get("image_name") in name_mapping:
                    seg["image_name"] = name_mapping[seg["image_name"]]
                if seg.get("end_image_name") in name_mapping:
                    seg["end_image_name"] = name_mapping[seg["end_image_name"]]
                    
            self.save()
            
        return (rename_count, idx) if return_next_idx else rename_count

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
            if item.is_file() and item.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
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
