# -*- coding: utf-8 -*-
"""
services/pipeline_scheduler.py
全局多工程无人值守流水线调度引擎。
集中所有可用浏览器 Worker 的算力，逐个歼灭工程队列中的视频任务，支持断点补漏与多项目自动接力。
"""

import logging
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, QTimer

logger = logging.getLogger(__name__)

class PipelineScheduler(QObject):
    # Signals
    pipeline_started_signal = pyqtSignal(int)          # total projects count
    pipeline_stopped_signal = pyqtSignal()
    pipeline_finished_signal = pyqtSignal(int, int)    # completed count, total count
    project_switched_signal = pyqtSignal(str, int, int) # project_name, current_idx, total
    project_completed_signal = pyqtSignal(str, int)     # project_name, project_idx
    points_exhausted_signal = pyqtSignal(int)          # total remaining pool points
    progress_updated_signal = pyqtSignal(str, int, int, int, int, int) # proj_name, cur_proj_idx, total_projs, completed_vids, total_vids, pool_pts

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.project_queue = []       # list of project dicts / names
        self.current_queue_index = 0
        self.is_running = False
        self.completed_projects_count = 0
        
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._check_current_project_progress)

    def set_queue(self, project_list):
        """Sets the list of projects to process in sequence."""
        self.project_queue = list(project_list)
        self.current_queue_index = 0
        self.completed_projects_count = 0

    def start(self):
        """Starts the multi-project automated pipeline."""
        if not self.project_queue:
            logger.warning("Pipeline queue is empty.")
            return False

        if not self.main_window or not hasattr(self.main_window, "plugin_server"):
            logger.warning("MainWindow or PluginServer not available.")
            return False

        self.is_running = True
        self.current_queue_index = 0
        self.completed_projects_count = 0
        self.pipeline_started_signal.emit(len(self.project_queue))
        
        logger.info(f"🚀 Global Pipeline started with {len(self.project_queue)} projects.")
        self._load_and_run_current_project()
        return True

    def stop(self):
        """Stops/pauses the automated pipeline."""
        self.is_running = False
        if self.monitor_timer.isActive():
            self.monitor_timer.stop()

        # Stop detail widget polling if active
        if self.main_window and hasattr(self.main_window, "detail_widget"):
            self.main_window.detail_widget.stop_auto_polling_dispatcher()

        self.pipeline_stopped_signal.emit()
        logger.info("⏸️ Global Pipeline stopped.")

    def _load_and_run_current_project(self):
        """Loads the current project in queue and starts dispatching tasks."""
        if not self.is_running:
            return

        if self.current_queue_index >= len(self.project_queue):
            # All projects in queue finished!
            self.is_running = False
            self.monitor_timer.stop()
            self.pipeline_finished_signal.emit(self.completed_projects_count, len(self.project_queue))
            logger.info("🎉 All projects in queue have completed successfully!")
            return

        proj_info = self.project_queue[self.current_queue_index]
        proj_name = proj_info.get("col1", "") if isinstance(proj_info, dict) else str(proj_info)
        
        logger.info(f"📂 Pipeline switching to project [{self.current_queue_index + 1}/{len(self.project_queue)}]: {proj_name}")
        self.project_switched_signal.emit(proj_name, self.current_queue_index + 1, len(self.project_queue))

        # Select project in MainWindow
        if self.main_window and hasattr(self.main_window, "select_project_by_info"):
            self.main_window.select_project_by_info(proj_info)

        # Start auto-polling dispatcher on detail widget
        if self.main_window and hasattr(self.main_window, "detail_widget"):
            self.main_window.detail_widget.start_auto_polling_dispatcher()

        # Start periodic progress checking
        if not self.monitor_timer.isActive():
            self.monitor_timer.start(3000) # Check every 3 seconds

    def _check_current_project_progress(self):
        """Checks if current project is 100% completed or if points are exhausted."""
        if not self.is_running or not self.main_window:
            return

        detail = getattr(self.main_window, "detail_widget", None)
        server = getattr(self.main_window, "plugin_server", None)

        if not detail or not detail.project_model or not detail.project_model.spanish_segments:
            return

        segments = detail.project_model.spanish_segments
        total_segs = len(segments)
        
        # Calculate completed count strictly based on real disk MP4 files
        completed_count = 0
        skipped_fail_count = 0
        for idx, seg in enumerate(segments):
            videos_dir = detail.project_path / "downloads" / "videos" if detail.project_path else Path("downloads/videos")
            mp4_file = videos_dir / f"{idx + 1:02d}.mp4"
            if mp4_file.exists() and mp4_file.stat().st_size > 0:
                completed_count += 1
                seg["copied"] = True
                seg["completed"] = True
            else:
                seg["copied"] = False
                seg["completed"] = False
                is_skip = (hasattr(detail, 'failed_skip_indices') and idx in detail.failed_skip_indices) or (hasattr(detail, 'segment_retry_counts') and detail.segment_retry_counts.get(idx, 0) >= 3)
                if is_skip:
                    skipped_fail_count += 1
                    if hasattr(detail, 'failed_skip_indices'):
                        detail.failed_skip_indices.add(idx)

        uncompleted_count = total_segs - (completed_count + skipped_fail_count)
        proj_info = self.project_queue[self.current_queue_index]
        proj_name = proj_info.get("col1", "") if isinstance(proj_info, dict) else str(proj_info)

        # Get pool points
        total_available_pts = 0
        if server:
            clients = server.get_online_clients()
            total_available_pts = sum(c.get("remaining_points", 0) for c in clients)

        # Emit real-time progress update signal
        self.progress_updated_signal.emit(
            proj_name,
            self.current_queue_index + 1,
            len(self.project_queue),
            completed_count,
            total_segs,
            total_available_pts
        )

        # Case 1: Current project is 100% completed!
        if uncompleted_count == 0:
            logger.info(f"✅ Project [{proj_name}] 100% completed ({completed_count}/{total_segs})! Advancing pipeline...")
            
            detail.stop_auto_polling_dispatcher()
            self.completed_projects_count += 1
            self.project_completed_signal.emit(proj_name, self.current_queue_index + 1)

            # Advance to next project after 1 second delay
            self.current_queue_index += 1
            QTimer.singleShot(1000, self._load_and_run_current_project)
            return

        # Case 2: Check total available points pool across all workers
        if server:
            clients = server.get_online_clients()
            total_available_pts = sum(c.get("remaining_points", 0) for c in clients if c.get("status") != "suspended")
            
            # If all workers are completely out of points (< 7 pts everywhere) and none are busy
            idle_workers_with_pts = [c for c in clients if c.get("status") == "idle" and c.get("remaining_points", 0) >= 7]
            busy_workers = [c for c in clients if c.get("status") == "busy"]

            if not idle_workers_with_pts and not busy_workers:
                logger.warning(f"⚠️ Total points exhausted across all {len(clients)} workers (Pool: {total_available_pts} pts). Pausing pipeline.")
                self.points_exhausted_signal.emit(total_available_pts)
                self.stop()
