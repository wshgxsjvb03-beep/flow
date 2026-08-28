# -*- coding: utf-8 -*-
import os
import json
from pathlib import Path

class StorageManager:
    """Manages the base storage directory and lists/creates projects."""
    
    CONFIG_FILE_NAME = ".app_config.json"
    
    def __init__(self, workspace_dir):
        self.workspace_dir = Path(workspace_dir)
        self.config_path = self.workspace_dir / self.CONFIG_FILE_NAME
        self.base_path = None
        self.load_config()

    def load_config(self):
        """Loads configuration including base storage path."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    base_str = config.get("base_path")
                    if base_str:
                        p = Path(base_str)
                        if p.exists() and p.is_dir():
                            self.base_path = p
            except Exception as e:
                print(f"Error loading config: {e}")
                self.base_path = None

    def save_config(self):
        """Saves current configuration to workspace file while preserving other settings."""
        config = {}
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        config["base_path"] = str(self.base_path) if self.base_path else ""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def set_base_path(self, path_str):
        """Sets a new base path and creates it if it doesn't exist."""
        p = Path(path_str)
        try:
            p.mkdir(parents=True, exist_ok=True)
            self.base_path = p
            self.save_config()
            return True
        except Exception as e:
            print(f"Error setting base path: {e}")
            return False

    def get_base_path(self):
        return self.base_path

    def get_relative_path(self, absolute_path):
        """Returns relative path from base_path as string.
        If base_path is not set or absolute_path is not under base_path, returns original path.
        """
        if not self.base_path:
            return str(absolute_path)
        try:
            abs_p = Path(absolute_path).resolve()
            base_p = self.base_path.resolve()
            return str(abs_p.relative_to(base_p))
        except ValueError:
            # Not a subpath
            return str(absolute_path)

    def resolve_path(self, relative_path):
        """Resolves relative path under base_path. If base_path is not set, returns relative_path as Path."""
        if not self.base_path:
            return Path(relative_path)
        return (self.base_path / relative_path).resolve()

    def list_projects(self):
        """Lists all project directories under base_path that match the naming pattern."""
        if not self.base_path or not self.base_path.exists():
            return []
            
        projects = []
        # Look for directories ending with "-flow"
        for item in self.base_path.iterdir():
            if item.is_dir() and item.name.endswith("-flow"):
                # We expect {index}_{col1}_{col7}-flow
                parts = item.name.split("_", 1)
                if len(parts) >= 2:
                    index_str = parts[0]
                    rest = parts[1][:-5]  # remove '-flow'
                    
                    sub_parts = rest.rsplit("_", 1)
                    col1 = sub_parts[0] if len(sub_parts) >= 2 else rest
                    col7 = sub_parts[1] if len(sub_parts) >= 2 else ""
                    
                    projects.append({
                        "id": item.name,
                        "path": str(item),
                        "index_str": index_str,
                        "col1": col1,
                        "col7": col7
                    })
        
        # Sort projects by index_str
        try:
            projects.sort(key=lambda x: int(x["index_str"]))
        except ValueError:
            projects.sort(key=lambda x: x["index_str"])
            
        return projects

    def create_project_dir(self, index, col1_val, col7_val):
        """Creates a project folder under base_path and returns the absolute Path.
        Format: {index:02d}_{col1_val}_{col7_val}-flow
        """
        if not self.base_path:
            raise ValueError("Base storage path is not set")
            
        # Clean folder name from invalid filesystem characters
        invalid_chars = '<>:"/\\|?*'
        c1 = "".join(c for c in col1_val if c not in invalid_chars).strip()
        c7 = "".join(c for c in col7_val if c not in invalid_chars).strip()
        
        # Limit length to avoid path length issues
        c1 = c1[:50]
        c7 = c7[:50]
        
        dir_name = f"{index:02d}_{c1}_{c7}-flow"
        proj_dir = self.base_path / dir_name
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a subfolder for downloads
        (proj_dir / "downloads").mkdir(parents=True, exist_ok=True)
        
        return proj_dir, dir_name
