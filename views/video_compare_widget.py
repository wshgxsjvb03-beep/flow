# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextEdit, QListWidget, QListWidgetItem,
                             QSplitter, QComboBox, QFrame, QProgressBar,
                             QMessageBox, QGroupBox, QScrollArea)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QDesktopServices

# Optional multimedia support - graceful fallback if not installed
_HAS_MULTIMEDIA = False
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except ImportError:
    QMediaPlayer = None
    QAudioOutput = None
    QVideoWidget = None


class VideoCompareWidget(QWidget):
    """Widget for comparing video segments against their original script text.
    
    Layout:
    - Top: Summary statistics bar (total, checked, unchecked, missing, marked delete)
    - Bottom-Left: Segment navigation list
    - Bottom-Right-Top: Video player
    - Bottom-Right-Bottom: Dual-column text comparison (original vs extracted)
    """
    
    videos_deleted = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_model = None
        self.project_path = None
        self.config_manager = None
        self.video_report = None  # From VideoChecker
        self.current_segment_index = -1
        self.init_ui()
    
    def init_ui(self):
        self.setStyleSheet("""
            QWidget#video_compare_root {
                background-color: #FAF6F0;
            }
            QLabel {
                font-size: 13px;
                color: #5D4037;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D2904C;
            }
            QPushButton:pressed {
                background-color: #B87635;
            }
            QPushButton:disabled {
                background-color: #D7CCC8;
                color: #A1887F;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #5D4037;
                font-size: 12px;
                padding: 2px;
            }
            QListWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #F5F5F5;
            }
            QListWidget::item:hover {
                background-color: #FFF8E1;
            }
            QListWidget::item:selected {
                background-color: #FFE0B2;
                color: #5D4037;
                font-weight: bold;
            }
            QComboBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                color: #5D4037;
            }
            QComboBox:hover {
                border: 1px solid #E0A96D;
            }
            QComboBox::drop-down {
                border: none;
            }
            QProgressBar {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                text-align: center;
                font-size: 11px;
                color: #5D4037;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #66BB6A;
                border-radius: 3px;
            }
        """)
        self.setObjectName("video_compare_root")
        
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)
        
        # ═══════════════════════════════════════════════════════
        # AREA 1: Top Summary Statistics Bar
        # ═══════════════════════════════════════════════════════
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        summary_layout.setSpacing(12)
        
        # Stats labels
        self.lbl_total = QLabel("总片段: 0")
        self.lbl_total.setStyleSheet("font-weight: bold; font-size: 13px;")
        summary_layout.addWidget(self.lbl_total)
        
        self.lbl_checked = QLabel("✅ 已核对: 0")
        self.lbl_checked.setStyleSheet("font-weight: bold; color: #2E7D32; font-size: 13px;")
        summary_layout.addWidget(self.lbl_checked)
        
        self.lbl_unchecked = QLabel("⚪ 待核对: 0")
        self.lbl_unchecked.setStyleSheet("font-weight: bold; color: #F57F17; font-size: 13px;")
        summary_layout.addWidget(self.lbl_unchecked)
        
        self.lbl_missing = QLabel("❌ 缺失: 0")
        self.lbl_missing.setStyleSheet("font-weight: bold; color: #C62828; font-size: 13px;")
        summary_layout.addWidget(self.lbl_missing)

        self.lbl_marked_delete = QLabel("🗑️ 待删除: 0")
        self.lbl_marked_delete.setStyleSheet("font-weight: bold; color: #DC2626; font-size: 13px;")
        summary_layout.addWidget(self.lbl_marked_delete)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(120)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        summary_layout.addWidget(self.progress_bar)
        
        summary_layout.addStretch()
        
        # Engine selector
        summary_layout.addWidget(QLabel("🔊 引擎:"))
        self.combo_engine = QComboBox()
        self.combo_engine.addItem("Gladia API", "gladia")
        self.combo_engine.addItem("ElevenLabs", "elevenlabs")
        self.combo_engine.setFixedWidth(140)
        summary_layout.addWidget(self.combo_engine)
        
        # Extract all button
        self.btn_extract_all = QPushButton("🚀 一键提取全部文案")
        self.btn_extract_all.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0369A1; }
            QPushButton:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_extract_all.setToolTip("调用 API 批量提取所有视频中的语音文案")
        self.btn_extract_all.clicked.connect(self.extract_all_texts)
        summary_layout.addWidget(self.btn_extract_all)

        # Batch delete marked videos button
        self.btn_delete_marked = QPushButton("🗑️ 一键删除标记视频")
        self.btn_delete_marked.setObjectName("btn_delete_marked")
        self.btn_delete_marked.setStyleSheet("""
            QPushButton#btn_delete_marked {
                background-color: #DC2626;
                color: white;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton#btn_delete_marked:hover { background-color: #B91C1C; }
            QPushButton#btn_delete_marked:disabled { background-color: #D7CCC8; color: #A1887F; }
        """)
        self.btn_delete_marked.setToolTip("一键彻底删除所有已标记句段的本地视频文件并重置状态")
        self.btn_delete_marked.clicked.connect(self.batch_delete_marked_videos)
        self.btn_delete_marked.setEnabled(False)
        summary_layout.addWidget(self.btn_delete_marked)
        
        root_layout.addWidget(summary_frame)
        
        # ═══════════════════════════════════════════════════════
        # AREA 2 & 3: Splitter (Left segment list | Right detail)
        # ═══════════════════════════════════════════════════════
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # ─── LEFT: Segment Navigation List ───
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        
        # Filter row
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("句段列表:"))
        filter_layout.addStretch()
        
        self.combo_filter = QComboBox()
        self.combo_filter.addItem("全部", "all")
        self.combo_filter.addItem("✅ 已归位", "relocated")
        self.combo_filter.addItem("⚪ 待核对", "unchecked")
        self.combo_filter.addItem("🟢 已核对", "checked")
        self.combo_filter.addItem("🗑️ 待删除", "marked_delete")
        self.combo_filter.addItem("❌ 缺失", "missing")
        self.combo_filter.setFixedWidth(110)
        self.combo_filter.currentIndexChanged.connect(self.apply_filter)
        filter_layout.addWidget(self.combo_filter)
        
        left_layout.addLayout(filter_layout)
        
        self.list_segments = QListWidget()
        self.list_segments.currentRowChanged.connect(self.on_segment_selected)
        left_layout.addWidget(self.list_segments)
        
        # Refresh button under list
        self.btn_refresh = QPushButton("🔄 刷新状态")
        self.btn_refresh.clicked.connect(self.refresh_data)
        left_layout.addWidget(self.btn_refresh)
        
        main_splitter.addWidget(left_widget)
        
        # ─── RIGHT: Detail comparison area ───
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        
        # Right area splits top (video) and bottom (text compare) vertically
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        
        # ── Video Player Area ──
        video_container = QWidget()
        video_container_layout = QVBoxLayout(video_container)
        video_container_layout.setContentsMargins(0, 0, 0, 0)
        video_container_layout.setSpacing(4)
        
        if _HAS_MULTIMEDIA:
            # Video widget (multimedia available)
            self.video_widget = QVideoWidget()
            self.video_widget.setMinimumHeight(180)
            self.video_widget.setStyleSheet("background-color: #1A1A2E; border-radius: 6px;")
            video_container_layout.addWidget(self.video_widget, stretch=1)
            
            # Media player
            self.media_player = QMediaPlayer()
            self.audio_output = QAudioOutput()
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setVideoOutput(self.video_widget)
        else:
            # Fallback: placeholder label when multimedia is not available
            self.video_widget = None
            self.media_player = None
            self.audio_output = None
            
            self._video_placeholder = QLabel("🎬 视频预览区域\n\n需安装 PyQt6-Multimedia 以启用内嵌播放器\n点击下方 [📂 打开] 使用系统播放器")
            self._video_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._video_placeholder.setMinimumHeight(180)
            self._video_placeholder.setStyleSheet("""
                QLabel {
                    background-color: #1A1A2E;
                    color: #A1887F;
                    border-radius: 6px;
                    font-size: 13px;
                    padding: 20px;
                }
            """)
            video_container_layout.addWidget(self._video_placeholder, stretch=1)
        
        # Player controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(6)
        
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setFixedWidth(80)
        self.btn_play.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.btn_play)
        
        self.lbl_video_time = QLabel("00:00 / 00:00")
        self.lbl_video_time.setStyleSheet("font-size: 11px; color: #8D6E63; font-weight: normal;")
        controls_layout.addWidget(self.lbl_video_time)
        
        controls_layout.addStretch()
        
        # Speed selector
        controls_layout.addWidget(QLabel("⚙"))
        self.combo_speed = QComboBox()
        self.combo_speed.addItem("0.5x", 0.5)
        self.combo_speed.addItem("1.0x", 1.0)
        self.combo_speed.addItem("1.25x", 1.25)
        self.combo_speed.addItem("1.5x", 1.5)
        self.combo_speed.addItem("2.0x", 2.0)
        self.combo_speed.setCurrentIndex(1)
        self.combo_speed.setFixedWidth(70)
        self.combo_speed.currentIndexChanged.connect(self.change_speed)
        controls_layout.addWidget(self.combo_speed)
        
        self.btn_open_file = QPushButton("📂 打开")
        self.btn_open_file.setFixedWidth(70)
        self.btn_open_file.setStyleSheet("background-color: #D7CCC8; color: #5D4037;")
        self.btn_open_file.clicked.connect(self.open_current_video_file)
        controls_layout.addWidget(self.btn_open_file)
        
        self.btn_play_external = QPushButton("▶ 外部播放")
        self.btn_play_external.setFixedWidth(90)
        self.btn_play_external.setStyleSheet("background-color: #7E57C2; color: white;")
        self.btn_play_external.clicked.connect(self.play_external)
        controls_layout.addWidget(self.btn_play_external)
        
        video_container_layout.addLayout(controls_layout)
        
        # Video file info label
        self.lbl_video_info = QLabel("未选择视频文件")
        self.lbl_video_info.setStyleSheet("font-size: 11px; color: #A1887F; font-weight: normal; font-style: italic;")
        video_container_layout.addWidget(self.lbl_video_info)
        
        right_splitter.addWidget(video_container)
        
        # ── Text Comparison Area ──
        compare_container = QWidget()
        compare_layout = QVBoxLayout(compare_container)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(6)
        
        # Segment info header
        self.lbl_segment_info = QLabel("请在左侧选择一个句段")
        self.lbl_segment_info.setStyleSheet("font-size: 13px; font-weight: bold; color: #5D4037; padding: 4px 0;")
        compare_layout.addWidget(self.lbl_segment_info)
        
        # Dual column comparison
        compare_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left column: Original Script
        left_compare = QWidget()
        left_compare_layout = QVBoxLayout(left_compare)
        left_compare_layout.setContentsMargins(0, 0, 4, 0)
        left_compare_layout.setSpacing(4)
        
        lbl_original_header = QLabel("📝 原始切分文案")
        lbl_original_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #5D4037; background-color: #EFEBE9; padding: 4px 8px; border-radius: 4px;")
        left_compare_layout.addWidget(lbl_original_header)
        
        self.txt_original = QTextEdit()
        self.txt_original.setReadOnly(True)
        self.txt_original.setPlaceholderText("原始文案将显示在这里...")
        self.txt_original.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                color: #3E2723;
                padding: 8px;
            }
        """)
        left_compare_layout.addWidget(self.txt_original)
        
        compare_splitter.addWidget(left_compare)
        
        # Right column: Extracted Text
        right_compare = QWidget()
        right_compare_layout = QVBoxLayout(right_compare)
        right_compare_layout.setContentsMargins(4, 0, 0, 0)
        right_compare_layout.setSpacing(4)
        
        lbl_extracted_header = QLabel("🔊 AI 提取文案")
        lbl_extracted_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #5D4037; background-color: #E3F2FD; padding: 4px 8px; border-radius: 4px;")
        right_compare_layout.addWidget(lbl_extracted_header)
        
        self.txt_extracted = QTextEdit()
        self.txt_extracted.setReadOnly(True)
        self.txt_extracted.setPlaceholderText("AI 提取的文案将显示在这里...\n\n请先在规则设置中配置 API Key，\n然后点击「🚀 一键提取全部文案」按钮。")
        self.txt_extracted.setStyleSheet("""
            QTextEdit {
                background-color: #FAFAFA;
                border: 1px solid #BBDEFB;
                border-radius: 4px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                color: #3E2723;
                padding: 8px;
            }
        """)
        right_compare_layout.addWidget(self.txt_extracted)
        
        compare_splitter.addWidget(right_compare)
        compare_splitter.setSizes([400, 400])
        
        compare_layout.addWidget(compare_splitter, stretch=1)
        
        # Similarity score & action buttons
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        
        self.lbl_similarity = QLabel("相似度: —")
        self.lbl_similarity.setStyleSheet("font-size: 13px; font-weight: bold; color: #8D6E63; padding: 2px 8px;")
        action_layout.addWidget(self.lbl_similarity)
        
        action_layout.addStretch()
        
        self.btn_extract_single = QPushButton("🔊 单句提取")
        self.btn_extract_single.setStyleSheet("background-color: #0284C7; color: white;")
        self.btn_extract_single.setEnabled(False)
        self.btn_extract_single.setToolTip("后续功能：调用 API 提取当前视频的语音文案")
        self.btn_extract_single.clicked.connect(self.extract_single_text)
        action_layout.addWidget(self.btn_extract_single)
        
        self.btn_mark_checked = QPushButton("✅ 标记核对无误")
        self.btn_mark_checked.setStyleSheet("background-color: #10B981; color: white;")
        self.btn_mark_checked.clicked.connect(self.mark_checked)
        action_layout.addWidget(self.btn_mark_checked)
        
        self.btn_mark_unchecked = QPushButton("↩ 取消核对")
        self.btn_mark_unchecked.setStyleSheet("background-color: #B0BEC5; color: #37474F;")
        self.btn_mark_unchecked.clicked.connect(self.mark_unchecked)
        action_layout.addWidget(self.btn_mark_unchecked)

        self.btn_mark_delete = QPushButton("🗑️ 标记删除")
        self.btn_mark_delete.setObjectName("btn_mark_delete")
        self.btn_mark_delete.setStyleSheet("""
            QPushButton#btn_mark_delete {
                background-color: #EF4444;
                color: white;
            }
            QPushButton#btn_mark_delete:hover {
                background-color: #DC2626;
            }
        """)
        self.btn_mark_delete.setToolTip("标记当前视频为错误/待重刷，之后可一键删除本地视频文件")
        self.btn_mark_delete.clicked.connect(self.toggle_mark_delete)
        action_layout.addWidget(self.btn_mark_delete)
        
        compare_layout.addLayout(action_layout)
        
        right_splitter.addWidget(compare_container)
        right_splitter.setSizes([280, 320])
        
        right_layout.addWidget(right_splitter)
        main_splitter.addWidget(right_widget)
        
        main_splitter.setSizes([250, 600])
        root_layout.addWidget(main_splitter, stretch=1)
        
        # Connect media player signals (only if multimedia is available)
        if _HAS_MULTIMEDIA and self.media_player:
            self.media_player.positionChanged.connect(self.update_position)
            self.media_player.durationChanged.connect(self.update_duration)
            self.media_player.playbackStateChanged.connect(self.update_play_button)
        
        self._current_video_path = None
        self._duration_ms = 0
    
    # ═══════════════════════════════════════════════════════
    # PUBLIC: Set project data
    # ═══════════════════════════════════════════════════════
    def set_project(self, project_model, project_path, config_manager=None):
        """Called when project is loaded/changed. Populates all data."""
        self.cleanup()
        self.project_model = project_model
        self.project_path = Path(project_path) if project_path else None
        self.config_manager = config_manager
        self.current_segment_index = -1
        self._current_video_path = None
        
        self.refresh_data()
    
    def cleanup(self):
        """Stops media player and active extraction worker thread cleanly."""
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass
                
        if hasattr(self, "_extraction_worker") and self._extraction_worker:
            try:
                if self._extraction_worker.isRunning():
                    self._extraction_worker.stop()
            except Exception:
                pass
            self._extraction_worker = None

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def hideEvent(self, event):
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass
        super().hideEvent(event)
    
    def refresh_data(self):
        """Re-runs video check and refreshes all UI elements."""
        if not self.project_model or not self.project_path:
            self._clear_all()
            return
        
        from services.video_checker import VideoChecker
        
        # Determine base_storage_path from parent
        main_win = self.window()
        base_storage_path = None
        if hasattr(main_win, 'storage_manager'):
            base_storage_path = main_win.storage_manager.get_base_path()
        
        self.video_report = VideoChecker.check_project_videos(
            self.project_model, self.project_path,
            base_storage_path=base_storage_path
        )
        
        self._populate_segment_list()
        self._update_summary()
        
        # Re-select current segment if valid
        if self.current_segment_index >= 0 and self.current_segment_index < self.list_segments.count():
            self.list_segments.setCurrentRow(self.current_segment_index)
        elif self.list_segments.count() > 0:
            self.list_segments.setCurrentRow(0)
        else:
            self._clear_detail()
    
    def _clear_all(self):
        """Clears all UI when no project is loaded."""
        self.list_segments.clear()
        self.lbl_total.setText("总片段: 0")
        self.lbl_checked.setText("✅ 已核对: 0")
        self.lbl_unchecked.setText("⚪ 待核对: 0")
        self.lbl_missing.setText("❌ 缺失: 0")
        self.lbl_marked_delete.setText("🗑️ 待删除: 0")
        if hasattr(self, "btn_delete_marked") and self.btn_delete_marked:
            self.btn_delete_marked.setEnabled(False)
            self.btn_delete_marked.setText("🗑️ 一键删除标记视频")
        self.progress_bar.setValue(0)
        self._clear_detail()
    
    def _clear_detail(self):
        """Clears the right detail panel."""
        self.txt_original.clear()
        self.txt_extracted.clear()
        self.lbl_segment_info.setText("请在左侧选择一个句段")
        self.lbl_similarity.setText("相似度: —")
        self.lbl_video_info.setText("未选择视频文件")
        self.lbl_video_time.setText("00:00 / 00:00")
        if hasattr(self, "btn_mark_delete") and self.btn_mark_delete:
            self.btn_mark_delete.setText("🗑️ 标记删除")
            self.btn_mark_delete.setEnabled(False)
        if self.media_player:
            self.media_player.stop()
        self._current_video_path = None
    
    # ═══════════════════════════════════════════════════════
    # Populate segment list
    # ═══════════════════════════════════════════════════════
    def _populate_segment_list(self):
        """Fills the left segment navigation list from video_report."""
        self.list_segments.blockSignals(True)
        self.list_segments.clear()
        
        if not self.video_report:
            self.list_segments.blockSignals(False)
            return
        
        segments = self.project_model.spanish_segments if self.project_model else []
        details = self.video_report.get("segments_detail", [])
        current_filter = self.combo_filter.currentData()
        
        for i, detail in enumerate(details):
            seg_data = segments[i] if i < len(segments) else {}
            
            # Video status
            is_found = detail.get("found", False)
            is_relocated = detail.get("already_in_target", False)
            is_missing = not is_found
            is_checked = seg_data.get("checked", False)
            is_marked_delete = seg_data.get("marked_for_deletion", False)
            
            # Apply filter
            if current_filter == "marked_delete" and not is_marked_delete:
                continue
            elif current_filter == "relocated" and not is_relocated:
                continue
            elif current_filter == "unchecked" and (is_checked or is_missing):
                continue
            elif current_filter == "checked" and not is_checked:
                continue
            elif current_filter == "missing" and not is_missing:
                continue
            
            seq_num = detail.get("index", i + 1)
            text = detail.get("text", "")
            truncated = text[:35] + "..." if len(text) > 35 else text
            
            # Check mismatch flag and similarity
            is_flagged = seg_data.get("mismatch_flagged", False)
            similarity = seg_data.get("similarity_score", 0)
            has_extracted = bool(seg_data.get("extracted_text", ""))
            
            # Build display label
            if is_marked_delete:
                video_icon = "🗑️"
                check_icon = "[待删除]"
            elif is_missing:
                video_icon = "❌"
                check_icon = "—"
            elif is_relocated:
                video_icon = "✅"
                if is_checked:
                    check_icon = "🟢"
                elif is_flagged:
                    check_icon = "🔴"
                elif has_extracted and similarity > 0 and similarity < 70:
                    check_icon = "🔴"
                elif has_extracted and similarity >= 70:
                    check_icon = "🟡"
                else:
                    check_icon = "⚪"
            else:
                video_icon = "⚠️"
                check_icon = "⚪"
            
            # Show similarity if available
            sim_label = f" ({similarity:.0f}%)" if has_extracted and similarity > 0 else ""
            label = f"{seq_num:02d}  {video_icon}  {check_icon}  {truncated}{sim_label}"
            
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i)  # Store real index
            
            # Color coding
            if is_marked_delete:
                item.setForeground(QColor("#DC2626"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip("⚠️ 该句段已标记为待删除，点击上方【一键删除标记视频】可清理本地文件并重新导出。")
            elif is_missing:
                item.setForeground(QColor("#C62828"))
            elif is_flagged or (has_extracted and similarity > 0 and similarity < 70):
                # Mismatch flagged or low similarity -> RED
                item.setForeground(QColor("#C62828"))
            elif is_checked:
                item.setForeground(QColor("#2E7D32"))
            elif is_relocated:
                item.setForeground(QColor("#5D4037"))
            else:
                item.setForeground(QColor("#F57F17"))
            
            self.list_segments.addItem(item)
        
        self.list_segments.blockSignals(False)
    
    def _update_summary(self):
        """Updates the top summary statistics bar."""
        if not self.video_report or not self.project_model:
            return
        
        segments = self.project_model.spanish_segments
        total = len(segments)
        checked_count = sum(1 for s in segments if s.get("checked", False))
        marked_delete_count = sum(1 for s in segments if s.get("marked_for_deletion", False))
        
        # Count based on video report
        missing = self.video_report.get("missing_count", 0)
        unchecked = total - checked_count - missing
        if unchecked < 0:
            unchecked = 0
        
        self.lbl_total.setText(f"总片段: {total}")
        self.lbl_checked.setText(f"✅ 已核对: {checked_count}")
        self.lbl_unchecked.setText(f"⚪ 待核对: {unchecked}")
        self.lbl_missing.setText(f"❌ 缺失: {missing}")
        self.lbl_marked_delete.setText(f"🗑️ 待删除: {marked_delete_count}")

        # Update batch delete button
        if hasattr(self, "btn_delete_marked") and self.btn_delete_marked:
            self.btn_delete_marked.setEnabled(marked_delete_count > 0)
            if marked_delete_count > 0:
                self.btn_delete_marked.setText(f"🗑️ 一键删除标记 ({marked_delete_count})")
            else:
                self.btn_delete_marked.setText("🗑️ 一键删除标记视频")
        
        # Progress
        pct = int(checked_count / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{pct}%")
    
    # ═══════════════════════════════════════════════════════
    # Segment selection handler
    # ═══════════════════════════════════════════════════════
    def on_segment_selected(self, row):
        """Called when user clicks a segment in the list."""
        if row < 0:
            self._clear_detail()
            return
        
        item = self.list_segments.item(row)
        if not item:
            return
        
        real_index = item.data(Qt.ItemDataRole.UserRole)
        self.current_segment_index = real_index
        self._load_segment_detail(real_index)
    
    def _load_segment_detail(self, index):
        """Loads video + text comparison for the given segment index."""
        if not self.video_report or not self.project_model:
            return
        
        details = self.video_report.get("segments_detail", [])
        segments = self.project_model.spanish_segments
        
        if index < 0 or index >= len(details) or index >= len(segments):
            return
        
        detail = details[index]
        seg = segments[index]
        seq_num = detail.get("index", index + 1)
        text = seg.get("text", "")
        char_count = len(text)
        
        # Duration label
        duration_label = ""
        if self.config_manager:
            duration_label = f" | 预期时长: {self.config_manager.get_duration_label(char_count)}"
        
        self.lbl_segment_info.setText(f"序号 {seq_num:02d} | {char_count} 字符{duration_label}")
        
        # Original text
        self.txt_original.setPlainText(text)
        
        # Extracted text (from segment data) - show diff highlighting
        extracted = seg.get("extracted_text", "")
        if extracted:
            # Show diff-highlighted HTML in both text areas
            orig_html, ext_html = self._build_diff_html(text, extracted)
            self.txt_original.setHtml(orig_html)
            self.txt_extracted.setHtml(ext_html)
            
            # Calculate and display similarity
            similarity = seg.get("similarity_score", 0)
            if similarity > 0:
                if similarity >= 90:
                    color = "#2E7D32"
                    icon = "🟢"
                elif similarity >= 70:
                    color = "#F57F17"
                    icon = "🟡"
                else:
                    color = "#C62828"
                    icon = "🔴"
                self.lbl_similarity.setText(f"相似度: {similarity:.1f}% {icon}")
                self.lbl_similarity.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color}; padding: 2px 8px;")
            else:
                self.lbl_similarity.setText("相似度: —")
                self.lbl_similarity.setStyleSheet("font-size: 13px; font-weight: bold; color: #8D6E63; padding: 2px 8px;")
        else:
            self.txt_extracted.clear()
            self.lbl_similarity.setText("相似度: —")
            self.lbl_similarity.setStyleSheet("font-size: 13px; font-weight: bold; color: #8D6E63; padding: 2px 8px;")

        # Update mark delete button
        if hasattr(self, "btn_mark_delete") and self.btn_mark_delete:
            self.btn_mark_delete.setEnabled(True)
            is_marked = seg.get("marked_for_deletion", False)
            if is_marked:
                self.btn_mark_delete.setText("↩ 取消待删")
                self.btn_mark_delete.setStyleSheet("""
                    QPushButton#btn_mark_delete {
                        background-color: #9CA3AF;
                        color: white;
                    }
                    QPushButton#btn_mark_delete:hover {
                        background-color: #6B7280;
                    }
                """)
                self.btn_mark_delete.setToolTip("取消当前句段的待删除标记")
            else:
                self.btn_mark_delete.setText("🗑️ 标记删除")
                self.btn_mark_delete.setStyleSheet("""
                    QPushButton#btn_mark_delete {
                        background-color: #EF4444;
                        color: white;
                    }
                    QPushButton#btn_mark_delete:hover {
                        background-color: #DC2626;
                    }
                """)
                self.btn_mark_delete.setToolTip("标记当前视频为错误/待重刷，之后可一键删除本地视频文件")
        
        # Load video
        is_found = detail.get("found", False)
        source_path = detail.get("source_path")
        
        if is_found and source_path and Path(str(source_path)).exists():
            video_path = Path(str(source_path))
            self._current_video_path = video_path
            file_size = detail.get("file_size", "未知")
            status = detail.get("status_text", "")
            self.lbl_video_info.setText(f"{status} | {video_path.name} | {file_size}")
            
            if self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl.fromLocalFile(str(video_path)))
            self.btn_play.setEnabled(_HAS_MULTIMEDIA)
            self.btn_extract_single.setEnabled(True)
        else:
            self._current_video_path = None
            self.lbl_video_info.setText("❌ 视频文件缺失")
            if self.media_player:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            self.btn_play.setEnabled(False)
            self.btn_extract_single.setEnabled(False)
    
    # ═══════════════════════════════════════════════════════
    # Video player controls
    # ═══════════════════════════════════════════════════════
    def toggle_play(self):
        if not self.media_player:
            self.play_external()
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()
    
    def update_play_button(self, state):
        if not _HAS_MULTIMEDIA:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play.setText("⏸ 暂停")
        else:
            self.btn_play.setText("▶ 播放")
    
    def update_position(self, position):
        total = self._duration_ms
        pos_str = self._format_time(position)
        dur_str = self._format_time(total)
        self.lbl_video_time.setText(f"{pos_str} / {dur_str}")
    
    def update_duration(self, duration):
        self._duration_ms = duration
    
    def change_speed(self):
        speed = self.combo_speed.currentData()
        if speed and self.media_player:
            self.media_player.setPlaybackRate(speed)
    
    def open_current_video_file(self):
        if self._current_video_path and self._current_video_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_video_path.parent)))
    
    def play_external(self):
        """Opens the current video file in the system's default video player."""
        if self._current_video_path and self._current_video_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_video_path)))
        else:
            QMessageBox.warning(self, "提示", "没有可播放的视频文件。")
    
    @staticmethod
    def _format_time(ms):
        s = ms // 1000
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"
    
    @staticmethod
    def _clean_word_for_display(word):
        """Strips leading/trailing punctuation and converts to lowercase for clean comparison display.
        Preserves Spanish accent characters (á, é, í, ó, ú, ü, ñ).
        Does NOT modify underlying project model data.
        """
        import re
        w = word.lower().strip()
        w = re.sub(r'^[^\w]+|[^\w]+$', '', w, flags=re.UNICODE)
        return w

    @staticmethod
    def _normalize_word_for_compare(word):
        """Internal helper to clean a word for matching only (ignores punctuation, case, accents).
        Does NOT modify original text data.
        """
        import re
        w = word.lower().strip()
        w = re.sub(r'[^\w]', '', w, flags=re.UNICODE)
        accent_map = str.maketrans({
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
            'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        })
        return w.translate(accent_map)

    @staticmethod
    def _build_diff_html(original, extracted):
        """Builds HTML diff for original and extracted text in-memory.
        Displays in clean all-lowercase format without punctuation.
        The reference script (left) is kept completely clean without annotations,
        while all issues (missing words, extra words, misread words) are marked
        exclusively in the AI extracted text (right).
        
        Returns:
            tuple: (original_html, extracted_html)
        """
        import difflib
        import html as html_module
        
        base_style = 'font-family:"Segoe UI",sans-serif; font-size:13px; line-height:1.6;'
        
        if not original and not extracted:
            return "", ""
        if not original:
            clean_ext = " ".join([VideoCompareWidget._clean_word_for_display(w) for w in extracted.split() if VideoCompareWidget._clean_word_for_display(w)])
            return "", f'<div style="{base_style}"><span style="color:#3E2723;">{html_module.escape(clean_ext)}</span></div>'
        if not extracted:
            clean_orig = " ".join([VideoCompareWidget._clean_word_for_display(w) for w in original.split() if VideoCompareWidget._clean_word_for_display(w)])
            return f'<div style="{base_style}"><span style="color:#3E2723;">{html_module.escape(clean_orig)}</span></div>', ""
        
        # Word tokens for display (all-lowercase, punctuation stripped)
        orig_words = [VideoCompareWidget._clean_word_for_display(w) for w in original.split()]
        orig_words = [w for w in orig_words if w]
        
        ext_words = [VideoCompareWidget._clean_word_for_display(w) for w in extracted.split()]
        ext_words = [w for w in ext_words if w]
        
        # Normalized word tokens for in-memory matching (accents also stripped)
        orig_norm = [VideoCompareWidget._normalize_word_for_compare(w) for w in orig_words]
        ext_norm = [VideoCompareWidget._normalize_word_for_compare(w) for w in ext_words]
        
        sm = difflib.SequenceMatcher(None, orig_norm, ext_norm)
        
        ext_parts = []
        
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                # Matching text - normal color
                text_e = " ".join(ext_words[j1:j2])
                ext_parts.append(f'<span style="color:#3E2723;">{html_module.escape(text_e)}</span>')
            elif tag == 'replace':
                # Misread/different text in audio - red background
                text_e = " ".join(ext_words[j1:j2])
                ext_parts.append(
                    f'<span style="background-color:#FFCDD2; color:#B71C1C; '
                    f'font-weight:bold; border-radius:2px; padding:1px 2px;">'
                    f'{html_module.escape(text_e)}</span>'
                )
            elif tag == 'delete':
                # In original but NOT in extracted (Missing words / 漏词) -> mark in extracted side
                text_o = " ".join(orig_words[i1:i2])
                ext_parts.append(
                    f'<span style="background-color:#FFECB3; color:#E65100; '
                    f'font-weight:bold; font-style:italic; border-radius:2px; padding:1px 3px;">'
                    f'[缺失: {html_module.escape(text_o)}]</span>'
                )
            elif tag == 'insert':
                # In extracted but NOT in original (Extra words spoken / 多说词) -> mark green
                text_e = " ".join(ext_words[j1:j2])
                ext_parts.append(
                    f'<span style="background-color:#C8E6C9; color:#1B5E20; '
                    f'font-weight:bold; border-radius:2px; padding:1px 2px;">'
                    f'{html_module.escape(text_e)}</span>'
                )
        
        # Left side: Clean reference text without any markup
        orig_clean_str = " ".join(orig_words)
        orig_html = f'<div style="{base_style}"><span style="color:#3E2723;">{html_module.escape(orig_clean_str)}</span></div>'
        
        # Right side: Annotated extracted text
        ext_html = f'<div style="{base_style}">{" ".join(ext_parts)}</div>'
        
        return orig_html, ext_html
    
    # ═══════════════════════════════════════════════════════
    # Check/Uncheck actions
    # ═══════════════════════════════════════════════════════
    def mark_checked(self):
        """Marks current segment as checked and auto-advances to next unchecked."""
        if self.current_segment_index < 0 or not self.project_model:
            return
        
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            segments[self.current_segment_index]["checked"] = True
            self.project_model.save()
            
            # Refresh UI
            self._populate_segment_list()
            self._update_summary()
            
            # Auto advance to next unchecked segment
            self._advance_to_next_unchecked()
    
    def mark_unchecked(self):
        """Removes checked mark from current segment."""
        if self.current_segment_index < 0 or not self.project_model:
            return
        
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            segments[self.current_segment_index]["checked"] = False
            self.project_model.save()
            
            self._populate_segment_list()
            self._update_summary()
            
            # Re-select the same segment
            for i in range(self.list_segments.count()):
                item = self.list_segments.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == self.current_segment_index:
                    self.list_segments.setCurrentRow(i)
                    break
    
    def toggle_mark_delete(self):
        """Toggles marked for deletion state for the currently selected segment."""
        if self.current_segment_index < 0 or not self.project_model:
            return
        
        segments = self.project_model.spanish_segments
        if self.current_segment_index < len(segments):
            seg = segments[self.current_segment_index]
            current_state = seg.get("marked_for_deletion", False)
            new_state = not current_state
            seg["marked_for_deletion"] = new_state
            
            if new_state:
                # When marked for deletion, reset checked status
                seg["checked"] = False
                seg["auto_checked"] = False
            
            self.project_model.save()
            
            # Refresh UI
            self._populate_segment_list()
            self._update_summary()
            
            if new_state:
                # Auto advance to next unchecked segment
                self._advance_to_next_unchecked()
            else:
                # Re-load current segment to update button state
                self._load_segment_detail(self.current_segment_index)

    def batch_delete_marked_videos(self):
        """Batch deletes local video files on disk for all segments marked for deletion."""
        if not self.project_model or not self.project_path:
            return
        
        segments = self.project_model.spanish_segments
        marked_indices = [i for i, s in enumerate(segments) if s.get("marked_for_deletion", False)]
        
        if not marked_indices:
            QMessageBox.information(self, "提示", "当前没有标记待删除的视频片段。")
            return
        
        # Build segment numbers string for confirmation
        indices_str = "、".join([f"{i+1:02d}" for i in marked_indices[:8]])
        if len(marked_indices) > 8:
            indices_str += f" 等共 {len(marked_indices)} 句"
        else:
            indices_str = f"第 {indices_str} 句（共 {len(marked_indices)} 句）"
        
        reply = QMessageBox.question(
            self, "确认一键删除",
            f"确定要删除已标记的 {len(marked_indices)} 个视频片段吗？\n\n"
            f"涉及句段: {indices_str}\n\n"
            f"• 本地视频文件将被彻底删除\n"
            f"• 对应句段状态将重置为【❌ 缺失】\n"
            f"• 在【文案、切分与提示词】导出批量生成 JSON 时将自动重新包含这些句段\n\n"
            f"⚠️ 此操作不可逆，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Stop multimedia player to release Windows file locks
        if hasattr(self, "media_player") and self.media_player:
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass
        
        from services.video_checker import VideoChecker
        
        main_win = self.window()
        base_storage_path = None
        if hasattr(main_win, 'storage_manager'):
            base_storage_path = main_win.storage_manager.get_base_path()
        
        res = VideoChecker.delete_segment_video_files(
            self.project_model, self.project_path, marked_indices, base_storage_path=base_storage_path
        )
        
        deleted_count = res.get("deleted_count", 0)
        errors = res.get("errors", [])
        
        # Emit signal to inform parent widgets (like ProjectDetailWidget) to update table
        self.videos_deleted.emit()
        
        # Refresh current video comparison data
        self.refresh_data()
        
        error_msg = ""
        if errors:
            error_msg = "\n\n⚠️ 部分文件删除出现警告:\n" + "\n".join(errors[:5])
        
        QMessageBox.information(
            self, "删除完成",
            f"✅ 成功清理了 {deleted_count} 个本地视频文件！\n"
            f"已重置对应句段状态为【缺失】。\n\n"
            f"💡 您可以前往第一标签页【文案、切分与提示词】点击「导出批量生成 JSON」重新导出生成。"
            f"{error_msg}"
        )
    
    def _advance_to_next_unchecked(self):
        """Finds and selects the next unchecked segment after current."""
        if not self.project_model:
            return
        
        segments = self.project_model.spanish_segments
        details = self.video_report.get("segments_detail", []) if self.video_report else []
        
        # Look for next unchecked segment with a video
        start = self.current_segment_index + 1
        for i in range(start, len(segments)):
            if not segments[i].get("checked", False):
                if i < len(details) and details[i].get("found", False):
                    # Find this index in the list widget
                    for row in range(self.list_segments.count()):
                        item = self.list_segments.item(row)
                        if item and item.data(Qt.ItemDataRole.UserRole) == i:
                            self.list_segments.setCurrentRow(row)
                            return
        
        # Wrap around from beginning
        for i in range(0, start):
            if not segments[i].get("checked", False):
                if i < len(details) and details[i].get("found", False):
                    for row in range(self.list_segments.count()):
                        item = self.list_segments.item(row)
                        if item and item.data(Qt.ItemDataRole.UserRole) == i:
                            self.list_segments.setCurrentRow(row)
                            return
    
    # ═══════════════════════════════════════════════════════
    # Filter
    # ═══════════════════════════════════════════════════════
    def apply_filter(self):
        """Re-populates segment list when filter changes."""
        self._populate_segment_list()
    
    # ═══════════════════════════════════════════════════════
    # Extract text - real implementation
    # ═══════════════════════════════════════════════════════
    def extract_all_texts(self):
        """Batch extraction: launches a background thread to extract text from all videos."""
        if not self.project_model or not self.video_report:
            return
        
        engine = self.combo_engine.currentData()
        engine_name = "Gladia API" if engine == "gladia" else "ElevenLabs"
        
        # Check API keys
        if not self.config_manager:
            QMessageBox.warning(self, "提示", "未找到配置管理器，请重新打开项目。")
            return
        
        if engine == "gladia" and not self.config_manager.gladia_api_keys:
            QMessageBox.warning(self, "缺少 API Key",
                "未配置 Gladia API Key！\n\n请点击主界面的「⚙️ 规则设置」按钮，\n在第 4 区域添加至少一个 Gladia API Key。")
            return
        elif engine == "elevenlabs" and not self.config_manager.elevenlabs_api_keys:
            QMessageBox.warning(self, "缺少 API Key",
                "未配置 ElevenLabs API Key！\n\n请点击主界面的「⚙️ 规则设置」按钮，\n在第 4 区域添加至少一个 ElevenLabs API Key。")
            return
        
        # Build list of segments to process (only those with found videos)
        segments = self.project_model.spanish_segments
        details = self.video_report.get("segments_detail", [])
        
        segments_to_process = []
        for i, detail in enumerate(details):
            if detail.get("found", False) and detail.get("source_path"):
                video_path = str(detail["source_path"])
                original_text = segments[i].get("text", "") if i < len(segments) else ""
                segments_to_process.append({
                    "segment_index": i,
                    "video_path": video_path,
                    "original_text": original_text,
                })
        
        if not segments_to_process:
            QMessageBox.information(self, "提示", "没有可提取的视频文件。请先确保视频已归位。")
            return
        
        # Confirmation
        reply = QMessageBox.question(
            self, "确认批量提取",
            f"将使用「{engine_name}」提取 {len(segments_to_process)} 个视频的语音文案。\n"
            f"语言: {self.config_manager.speech_language}\n\n"
            f"此操作将调用 API 并消耗额度，确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Disable buttons during extraction
        self.btn_extract_all.setEnabled(False)
        self.btn_extract_all.setText("⏳ 提取中...")
        self.btn_extract_single.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        
        # Launch worker thread
        from services.speech_extractor import ExtractionWorker
        
        if hasattr(self, "_extraction_worker") and self._extraction_worker:
            try:
                if self._extraction_worker.isRunning():
                    self._extraction_worker.stop()
            except Exception:
                pass
            self._extraction_worker = None
        
        language = getattr(self.config_manager, "speech_language", "es")
        
        self._extraction_worker = ExtractionWorker(
            segments_to_process, engine, self.config_manager, language
        )
        self._extraction_worker.progress.connect(self._on_extraction_progress)
        self._extraction_worker.segment_done.connect(self._on_segment_extracted)
        self._extraction_worker.finished.connect(self._on_extraction_finished)
        self._extraction_worker.finished.connect(self._extraction_worker.deleteLater)
        self._extraction_worker.start()
    
    def _on_extraction_progress(self, current, total, status_msg):
        """Updates progress bar and status during batch extraction."""
        pct = int(current / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"提取 {current}/{total}")
        self.lbl_video_info.setText(status_msg)
    
    def _on_segment_extracted(self, segment_index, extracted_text, similarity_score):
        """Called when a single segment extraction completes. Saves to metadata.
        Also auto-marks: >=90% similarity -> checked; <70% -> flagged as mismatch."""
        if not self.project_model:
            return
        
        segments = self.project_model.spanish_segments
        if segment_index < len(segments):
            segments[segment_index]["extracted_text"] = extracted_text
            segments[segment_index]["similarity_score"] = similarity_score
            segments[segment_index]["extraction_engine"] = self.combo_engine.currentData()
            
            import datetime
            segments[segment_index]["extraction_time"] = datetime.datetime.now().isoformat()
            
            # Auto-mark based on similarity
            if extracted_text:  # Only auto-mark if extraction succeeded
                if similarity_score >= 90:
                    # High similarity -> auto-check as OK
                    segments[segment_index]["checked"] = True
                    segments[segment_index]["auto_checked"] = True
                elif similarity_score < 70:
                    # Low similarity -> flag as mismatch
                    segments[segment_index]["checked"] = False
                    segments[segment_index]["mismatch_flagged"] = True
                else:
                    # Medium similarity -> needs manual review
                    segments[segment_index]["checked"] = False
                    segments[segment_index]["mismatch_flagged"] = False
            
            # Save immediately so progress isn't lost on crash
            self.project_model.save()
        
        # If this is the currently viewed segment, refresh the detail view
        if self.current_segment_index == segment_index:
            self._load_segment_detail(segment_index)
    
    def _on_extraction_finished(self, success_count, total_count, errors):
        """Called when batch extraction completes."""
        # Re-enable buttons
        self.btn_extract_all.setEnabled(True)
        self.btn_extract_all.setText("🚀 一键提取全部文案")
        self.btn_extract_single.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        
        # Refresh UI
        self._populate_segment_list()
        self._update_summary()
        
        # Count auto-marked results
        segments = self.project_model.spanish_segments if self.project_model else []
        auto_checked = sum(1 for s in segments if s.get("auto_checked", False))
        flagged = sum(1 for s in segments if s.get("mismatch_flagged", False))
        
        # Show result
        error_text = ""
        if errors:
            error_text = "\n\n❌ 失败详情:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                error_text += f"\n... 及其他 {len(errors) - 10} 个错误"
        
        auto_mark_info = ""
        if auto_checked > 0 or flagged > 0:
            auto_mark_info = (
                f"\n\n🤖 自动标注结果:\n"
                f"✅ 相似度≥90% 自动通过: {auto_checked} 段\n"
                f"🔴 相似度<70% 差异标红: {flagged} 段"
            )
        
        QMessageBox.information(
            self, "提取完成",
            f"✅ 成功: {success_count}/{total_count}\n"
            f"❌ 失败: {total_count - success_count}/{total_count}"
            f"{auto_mark_info}"
            f"{error_text}"
        )
        
        self._extraction_worker = None
    
    def extract_single_text(self):
        """Extracts text from the currently selected segment's video."""
        if self.current_segment_index < 0 or not self.project_model or not self.video_report:
            return
        
        engine = self.combo_engine.currentData()
        engine_name = "Gladia API" if engine == "gladia" else "ElevenLabs"
        
        # Check API keys
        if not self.config_manager:
            QMessageBox.warning(self, "提示", "未找到配置管理器。")
            return
        
        if engine == "gladia" and not self.config_manager.gladia_api_keys:
            QMessageBox.warning(self, "缺少 API Key",
                "未配置 Gladia API Key！\n请在「⚙️ 规则设置」中添加。")
            return
        elif engine == "elevenlabs" and not self.config_manager.elevenlabs_api_keys:
            QMessageBox.warning(self, "缺少 API Key",
                "未配置 ElevenLabs API Key！\n请在「⚙️ 规则设置」中添加。")
            return
        
        details = self.video_report.get("segments_detail", [])
        segments = self.project_model.spanish_segments
        
        idx = self.current_segment_index
        if idx >= len(details) or idx >= len(segments):
            return
        
        detail = details[idx]
        if not detail.get("found", False) or not detail.get("source_path"):
            QMessageBox.warning(self, "提示", "当前句段的视频文件缺失，无法提取。")
            return
        
        video_path = str(detail["source_path"])
        original_text = segments[idx].get("text", "")
        language = getattr(self.config_manager, "speech_language", "es")
        
        # Disable button and show progress
        self.btn_extract_single.setEnabled(False)
        self.btn_extract_single.setText("⏳ 提取中...")
        self.lbl_video_info.setText(f"正在使用 {engine_name} 提取第 {idx + 1} 段...")
        
        # Use QApplication.processEvents to update UI before blocking call
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        
        from services.speech_extractor import SpeechExtractor
        
        result = SpeechExtractor.extract_with_retry(
            video_path, engine, self.config_manager, language
        )
        
        # Re-enable button
        self.btn_extract_single.setEnabled(True)
        self.btn_extract_single.setText("🔊 单句提取")
        
        if result["success"]:
            extracted_text = result["text"]
            similarity = SpeechExtractor.calculate_similarity(original_text, extracted_text)
            
            # Save to segment
            segments[idx]["extracted_text"] = extracted_text
            segments[idx]["similarity_score"] = similarity
            segments[idx]["extraction_engine"] = engine
            
            import datetime
            segments[idx]["extraction_time"] = datetime.datetime.now().isoformat()
            
            self.project_model.save()
            
            # Refresh display
            self._load_segment_detail(idx)
            self._update_summary()
            
            QMessageBox.information(self, "提取成功",
                f"✅ 第 {idx + 1} 段文案提取成功！\n相似度: {similarity:.1f}%")
        else:
            self.lbl_video_info.setText(f"❌ 提取失败: {result['error']}")
            QMessageBox.warning(self, "提取失败",
                f"第 {idx + 1} 段文案提取失败：\n{result['error']}")

