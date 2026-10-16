# -*- coding: utf-8 -*-
import json
import uuid
import os
from pathlib import Path

class BatchProjectModel:
    def __init__(self, workspace_dir):
        self.workspace_dir = Path(workspace_dir)
        self.batch_dir = self.workspace_dir / "batch_projects"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.projects = []
        self.load_all()

    def load_all(self):
        self.projects = []
        for file in self.batch_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.projects.append(data)
            except Exception as e:
                print(f"Error loading {file}: {e}")
        # Sort by created time
        self.projects.sort(key=lambda x: x.get("created_at", 0))

    def create_project(self, name, images):
        import time
        pid = "batch-" + uuid.uuid4().hex[:8]
        project = {
            "id": pid,
            "name": name,
            "created_at": time.time(),
            "images": images,  # List of dicts: {"path": "...", "prompt": "", "duration": 8}
            "template_id": "",
            "points_cost": 50,
            "images_per_block": 4,
            "duration": 8
        }
        self.projects.append(project)
        self.save_project(project)
        return project

    def save_project(self, project):
        file_path = self.batch_dir / f"{project['id']}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(project, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving {file_path}: {e}")

    def delete_project(self, project_id):
        file_path = self.batch_dir / f"{project_id}.json"
        if file_path.exists():
            file_path.unlink()
        self.projects = [p for p in self.projects if p["id"] != project_id]
