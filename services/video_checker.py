# -*- coding: utf-8 -*-
import os
import shutil
import re
from pathlib import Path

class VideoChecker:
    """Service to check generated video completeness and relocate video files,
    strictly scoped to specific project directories and identifiers.
    """

    @staticmethod
    def get_file_size_str(filepath):
        try:
            size_bytes = os.path.getsize(filepath)
            if size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        except Exception:
            return "未知"

    @staticmethod
    def is_matching_video_file(filename, seq_num):
        """Strictly checks if a video filename matches a segment index (seq_num).
        Ensures digit boundaries to prevent false positives like matching 106 for index 6.
        """
        ext = Path(filename).suffix.lower()
        if ext not in ['.mp4', '.mov', '.webm', '.avi']:
            return False

        stem = Path(filename).stem
        
        # Exact match: "01", "1"
        if stem.strip() == f"{seq_num:02d}" or stem.strip() == str(seq_num):
            return True

        # Boundary regex match:
        pattern = re.compile(rf'(?:^|[_\-\s\(\[])0*{seq_num}(?=[_\-\s\.\)\]]|$)', re.IGNORECASE)
        return bool(pattern.search(stem))

    @staticmethod
    def find_project_folders(search_dir, project_id, index, col1_name):
        """Finds subdirectories in search_dir that specifically belong to this project."""
        if not search_dir or not search_dir.exists() or not search_dir.is_dir():
            return []

        idx_prefix = f"{index:02d}_"
        matched = []

        try:
            for entry in search_dir.iterdir():
                if entry.is_dir():
                    name_lower = entry.name.lower()
                    pid_lower = project_id.lower()
                    
                    # 1. Exact match on project_id or project_id without suffix
                    if name_lower == pid_lower or name_lower == pid_lower.replace("-flow", ""):
                        matched.append(entry)
                        continue
                        
                    # 2. Match index prefix (e.g. "02_") and col1_name
                    if entry.name.startswith(idx_prefix):
                        if not col1_name or col1_name.lower() in name_lower:
                            matched.append(entry)
                            continue
                            
                    # 3. Match folder containing full project_id string
                    if pid_lower in name_lower or pid_lower.replace("-flow", "") in name_lower:
                        matched.append(entry)
                        continue
        except Exception as e:
            print(f"Error finding project folders in {search_dir}: {e}")

        return matched

    @staticmethod
    def check_project_videos(project_model, project_path, base_storage_path=None, custom_search_dir=None):
        """Scans disk for generated video files STRICTLY scoped to:
        1. Post-relocation path (Project internal): {project_path}/downloads/videos/
        2. Pre-relocation path (Base download): {base_storage_path}/Flow/{project_id}/ (or custom_search_dir)
        """
        if not project_model or not project_model.spanish_segments:
            return {
                "project_id": getattr(project_model, "project_id", Path(project_path).name),
                "project_name": getattr(project_model, "col1_name", Path(project_path).name),
                "project_path": str(project_path),
                "total_segments": 0,
                "found_count": 0,
                "already_count": 0,
                "pending_count": 0,
                "missing_count": 0,
                "completion_rate": 0.0,
                "segments_detail": [],
                "post_relocate_dir": str(Path(project_path) / "downloads" / "videos"),
                "pre_relocate_dir": ""
            }

        segments = project_model.spanish_segments
        total_segments = len(segments)
        project_id = project_model.project_id
        index = getattr(project_model, "index", 1)
        col1_name = getattr(project_model, "col1_name", "")
        project_path_obj = Path(project_path)
        
        # 1. Post-relocation directory inside project folder
        post_relocate_dir = project_path_obj / "downloads" / "videos"
        post_relocate_dir.mkdir(parents=True, exist_ok=True)

        # 2. Pre-relocation directory (Flow download folder under base_storage_path)
        pre_relocate_search_dirs = []
        
        if custom_search_dir:
            cd = Path(custom_search_dir)
            if cd.exists():
                pre_relocate_search_dirs.append(cd)
        else:
            # Determine base storage path if not explicitly provided
            if not base_storage_path:
                base_storage_path = project_path_obj.parent
            else:
                base_storage_path = Path(base_storage_path)
                
            flow_base = base_storage_path / "Flow"
            if flow_base.exists() and flow_base.is_dir():
                # Locate specific project folders inside base_storage_path/Flow/
                matched_subfolders = VideoChecker.find_project_folders(flow_base, project_id, index, col1_name)
                for sf in matched_subfolders:
                    pre_relocate_search_dirs.append(sf)
                
                # Also check direct folder Flow/project_id if not caught above
                direct_proj_flow = flow_base / project_id
                if direct_proj_flow.exists() and direct_proj_flow.is_dir():
                    if direct_proj_flow.resolve() not in [p.resolve() for p in pre_relocate_search_dirs]:
                        pre_relocate_search_dirs.append(direct_proj_flow)
                        
                # Also include Flow root directory as search dir if no subfolder found
                if not pre_relocate_search_dirs:
                    pre_relocate_search_dirs.append(flow_base)

        pre_relocate_display_str = str(pre_relocate_search_dirs[0]) if pre_relocate_search_dirs else str(Path(base_storage_path or project_path_obj.parent) / "Flow" / project_id)

        # 3. Match segment files STRICTLY inside Post-relocation vs Pre-relocation
        segments_detail = []
        already_count = 0
        pending_count = 0
        missing_count = 0

        for idx, seg in enumerate(segments):
            seq_num = idx + 1
            idx_str = f"{seq_num:02d}"
            text = seg.get("text", "")
            download_name = f"{idx_str}.mp4"
            target_path = post_relocate_dir / download_name

            found_file = None
            is_already_in_target = False

            # A. Check Post-relocation directory ({project_path}/downloads/videos/)
            if target_path.exists() and target_path.is_file():
                found_file = target_path
                is_already_in_target = True
            else:
                # Scan files in post_relocate_dir for matching filename (e.g. 01.mp4, 01_foo.mp4)
                if post_relocate_dir.exists():
                    try:
                        for entry in post_relocate_dir.iterdir():
                            if entry.is_file() and VideoChecker.is_matching_video_file(entry.name, seq_num):
                                found_file = entry
                                is_already_in_target = True
                                break
                    except Exception:
                        pass

            # B. If not in Post-relocation directory, check Pre-relocation directories
            if not found_file:
                for p_dir in pre_relocate_search_dirs:
                    if not p_dir.exists() or not p_dir.is_dir():
                        continue
                    
                    # Direct check 01.mp4
                    direct_file = p_dir / download_name
                    if direct_file.exists() and direct_file.is_file():
                        found_file = direct_file
                        is_already_in_target = False
                        break

                    # Scan files inside Pre-relocation directory
                    try:
                        for entry in p_dir.iterdir():
                            if entry.is_file() and VideoChecker.is_matching_video_file(entry.name, seq_num):
                                found_file = entry
                                is_already_in_target = False
                                break
                    except Exception:
                        pass

                    if found_file:
                        break

            # C. Record segment report
            if found_file:
                file_size = VideoChecker.get_file_size_str(found_file)
                if is_already_in_target:
                    already_count += 1
                    status_text = "✅ 已归位"
                else:
                    pending_count += 1
                    status_text = "⚠️ 待归位"

                segments_detail.append({
                    "index": seq_num,
                    "text": text,
                    "download_name": download_name,
                    "found": True,
                    "already_in_target": is_already_in_target,
                    "status_text": status_text,
                    "source_path": found_file,
                    "target_path": target_path,
                    "file_size": file_size
                })
            else:
                missing_count += 1
                segments_detail.append({
                    "index": seq_num,
                    "text": text,
                    "download_name": download_name,
                    "found": False,
                    "already_in_target": False,
                    "status_text": "❌ 缺失",
                    "source_path": None,
                    "target_path": target_path,
                    "file_size": "-"
                })

        found_count = already_count + pending_count
        completion_rate = (found_count / total_segments * 100.0) if total_segments > 0 else 0.0

        return {
            "project_id": project_id,
            "project_name": col1_name or project_id,
            "project_path": str(project_path),
            "total_segments": total_segments,
            "found_count": found_count,
            "already_count": already_count,
            "pending_count": pending_count,
            "missing_count": missing_count,
            "completion_rate": completion_rate,
            "segments_detail": segments_detail,
            "post_relocate_dir": str(post_relocate_dir),
            "pre_relocate_dir": pre_relocate_display_str
        }

    @staticmethod
    def check_all_projects(projects_list, base_storage_path):
        """Scans ALL projects in projects_list and generates a consolidated batch report."""
        from models.project_model import ProjectModel

        projects_reports = []
        total_projects = len(projects_list)
        fully_complete_count = 0
        pending_count_total = 0
        missing_count_total = 0

        for proj in projects_list:
            proj_path = proj.get("path")
            if not proj_path or not Path(proj_path).exists():
                continue
                
            proj_model = ProjectModel(proj_path)
            report = VideoChecker.check_project_videos(proj_model, proj_path, base_storage_path=base_storage_path)
            projects_reports.append(report)

            if report["completion_rate"] >= 100.0 and report["pending_count"] == 0:
                fully_complete_count += 1
            
            pending_count_total += report["pending_count"]
            missing_count_total += report["missing_count"]

        return {
            "total_projects": total_projects,
            "fully_complete_count": fully_complete_count,
            "pending_count_total": pending_count_total,
            "missing_count_total": missing_count_total,
            "projects_reports": projects_reports,
            "base_storage_path": str(base_storage_path) if base_storage_path else ""
        }

    @staticmethod
    def relocate_found_videos(report):
        """Relocates (moves) all pending videos from pre-relocation directory (e.g. BaseDir/Flow/01_project-flow)
        into the project's target videos folder.
        """
        details = report.get("segments_detail", [])
        moved_count = 0
        already_count = 0
        error_msgs = []

        for item in details:
            if not item.get("found") or not item.get("source_path"):
                continue

            src = Path(item["source_path"])
            dst = Path(item["target_path"])

            if src.resolve() == dst.resolve() or item.get("already_in_target"):
                already_count += 1
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                item["source_path"] = dst
                item["already_in_target"] = True
                item["status_text"] = "✅ 已归位"
                moved_count += 1
            except Exception as e:
                error_msgs.append(f"移动 {src.name} 失败: {e}")

        # Update summary counters in report
        if moved_count > 0:
            report["already_count"] = report.get("already_count", 0) + moved_count
            report["pending_count"] = max(0, report.get("pending_count", 0) - moved_count)

        return {
            "moved_count": moved_count,
            "already_count": already_count,
            "errors": error_msgs
        }

    @staticmethod
    def relocate_batch_videos(batch_report):
        """Relocates pending videos for ALL projects in batch_report."""
        total_moved = 0
        total_already = 0
        all_errors = []

        for proj_report in batch_report.get("projects_reports", []):
            if proj_report.get("pending_count", 0) > 0:
                res = VideoChecker.relocate_found_videos(proj_report)
                total_moved += res["moved_count"]
                total_already += res["already_count"]
                all_errors.extend(res["errors"])

        # Update batch summary
        if total_moved > 0:
            batch_report["pending_count_total"] = max(0, batch_report.get("pending_count_total", 0) - total_moved)
            # Re-evaluate fully complete count
            fc_count = 0
            for r in batch_report.get("projects_reports", []):
                if r["completion_rate"] >= 100.0 and r["pending_count"] == 0:
                    fc_count += 1
            batch_report["fully_complete_count"] = fc_count

        return {
            "moved_count": total_moved,
            "already_count": total_already,
            "errors": all_errors
        }

    @staticmethod
    def delete_segment_video_files(project_model, project_path, segment_indices, base_storage_path=None):
        """Deletes video files on disk for specific segment indices and resets their metadata."""
        if not project_model or not project_path or not segment_indices:
            return {"deleted_count": 0, "errors": []}

        project_path_obj = Path(project_path)
        post_relocate_dir = project_path_obj / "downloads" / "videos"
        
        # Determine pre-relocate search directories
        pre_relocate_search_dirs = []
        if not base_storage_path:
            base_storage_path = project_path_obj.parent
        else:
            base_storage_path = Path(base_storage_path)

        flow_base = base_storage_path / "Flow"
        if flow_base.exists() and flow_base.is_dir():
            project_id = getattr(project_model, "project_id", project_path_obj.name)
            index = getattr(project_model, "index", 1)
            col1_name = getattr(project_model, "col1_name", "")
            matched_subfolders = VideoChecker.find_project_folders(flow_base, project_id, index, col1_name)
            for sf in matched_subfolders:
                pre_relocate_search_dirs.append(sf)
            direct_proj_flow = flow_base / project_id
            if direct_proj_flow.exists() and direct_proj_flow.is_dir():
                if direct_proj_flow.resolve() not in [p.resolve() for p in pre_relocate_search_dirs]:
                    pre_relocate_search_dirs.append(direct_proj_flow)
            # Note: Do NOT fall back to flow_base root during deletion to prevent deleting videos belonging to other projects.

        deleted_files_count = 0
        error_msgs = []
        segments = project_model.spanish_segments if project_model else []

        for idx in segment_indices:
            if idx < 0 or idx >= len(segments):
                continue
            
            seq_num = idx + 1
            files_to_delete = set()

            # 1. Look in post-relocate directory
            if post_relocate_dir.exists():
                try:
                    for entry in post_relocate_dir.iterdir():
                        if entry.is_file() and VideoChecker.is_matching_video_file(entry.name, seq_num):
                            files_to_delete.add(entry)
                except Exception as e:
                    error_msgs.append(f"扫描目录 {post_relocate_dir} 失败: {e}")

            # 2. Look in pre-relocate directories
            for p_dir in pre_relocate_search_dirs:
                if p_dir.exists() and p_dir.is_dir():
                    try:
                        for entry in p_dir.iterdir():
                            if entry.is_file() and VideoChecker.is_matching_video_file(entry.name, seq_num):
                                files_to_delete.add(entry)
                    except Exception as e:
                        error_msgs.append(f"扫描目录 {p_dir} 失败: {e}")

            # 3. Delete files
            for file_path in files_to_delete:
                try:
                    if file_path.exists():
                        file_path.unlink()
                        deleted_files_count += 1
                except Exception as e:
                    error_msgs.append(f"删除文件 {file_path.name} 失败: {e}")

            # 4. Reset segment metadata
            seg = segments[idx]
            seg["marked_for_deletion"] = False
            seg["checked"] = False
            seg["auto_checked"] = False
            seg["mismatch_flagged"] = False
            seg["extracted_text"] = ""
            seg["similarity_score"] = 0
            seg["extraction_engine"] = ""
            seg["copied"] = False
            seg["completed"] = False

        try:
            project_model.save()
        except Exception as e:
            error_msgs.append(f"保存元数据失败: {e}")

        return {
            "deleted_count": deleted_files_count,
            "errors": error_msgs
        }

