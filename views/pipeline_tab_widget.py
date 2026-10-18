# -*- coding: utf-8 -*-
"""
views/pipeline_tab_widget.py
全局无人值守流水线控制台 — 独立 Tab 页
分步执行：📸 上传图片 → 📋 下发任务 → ▶️ 监控执行
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QSpinBox, QCheckBox, QHeaderView,
                             QFrame, QProgressBar, QMessageBox, QSplitter,
                             QGroupBox, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from pathlib import Path
import json
import logging
import uuid
import time
import threading
import ctypes
import ctypes.wintypes
import sys

logger = logging.getLogger(__name__)

# 积分消耗表: 时长(秒) -> 消耗积分
DURATION_COST = {4: 7, 5: 7, 6: 10, 8: 12, 10: 15}

# ──────────────────────────────────────────
# Win32 桌面自动化：操控原生文件选择器对话框
# ──────────────────────────────────────────
_user32 = ctypes.windll.user32 if sys.platform == 'win32' else None
_WNDENUMPROC = (ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
                if sys.platform == 'win32' else None)
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5


class FileDialogAutomation:
    """使用 Win32 API 自动填写原生文件对话框"""

    @staticmethod
    def find_dialog(timeout=15):
        """等待并找到 Windows 文件打开对话框"""
        if _user32 is None:
            return 0
        start = time.time()
        while time.time() - start < timeout:
            for title in ["打开", "Open", "选择要上传的文件"]:
                hwnd = _user32.FindWindowW("#32770", title)
                if hwnd and _user32.IsWindowVisible(hwnd):
                    return hwnd
            time.sleep(0.3)
        return 0

    @staticmethod
    def _find_filename_edit(hwnd):
        """在对话框中找到文件名输入框 (ComboBoxEx32 > ComboBox > Edit)"""
        result = [0]

        def _enum(child, _):
            cls = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(child, cls, 256)
            if cls.value == "Edit":
                parent = _user32.GetParent(child)
                pcls = ctypes.create_unicode_buffer(256)
                _user32.GetClassNameW(parent, pcls, 256)
                if pcls.value in ("ComboBox", "ComboBoxEx32"):
                    result[0] = child
                    return False
                # 也检查 control id 1148 (经典文件对话框)
                cid = _user32.GetDlgCtrlID(child)
                if cid == 1148:
                    result[0] = child
                    return False
            return True

        _user32.EnumChildWindows(hwnd, _WNDENUMPROC(_enum), 0)
        return result[0]

    @staticmethod
    def _find_open_button(hwnd):
        """找到'打开(O)'按钮"""
        result = [0]

        def _enum(child, _):
            cls = ctypes.create_unicode_buffer(256)
            _user32.GetClassNameW(child, cls, 256)
            if cls.value == "Button":
                txt = ctypes.create_unicode_buffer(256)
                _user32.GetWindowTextW(child, txt, 256)
                t = txt.value
                if ("打开" in t or "Open" in t) and "取消" not in t and "Cancel" not in t:
                    result[0] = child
                    return False
            return True

        _user32.EnumChildWindows(hwnd, _WNDENUMPROC(_enum), 0)
        return result[0]

    @classmethod
    def fill_and_confirm(cls, filepath, timeout=15):
        """
        等待文件对话框出现 → 填入路径 → 点击打开。
        返回 (success: bool, message: str)
        """
        if _user32 is None:
            return False, '原生文件对话框自动填写仅支持 Windows，请使用全局托管模式的插件上传'
        hwnd = cls.find_dialog(timeout)
        if not hwnd:
            return False, "文件对话框未出现"

        time.sleep(0.5)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

        edit = cls._find_filename_edit(hwnd)
        if not edit:
            return False, "未找到文件名输入框"

        # 设置文件路径
        _user32.SendMessageW(edit, WM_SETTEXT, 0, filepath)
        time.sleep(0.3)

        # 点击打开按钮
        btn = cls._find_open_button(hwnd)
        if btn:
            _user32.SendMessageW(btn, BM_CLICK, 0, 0)
            return True, "已填入路径并点击打开"

        # 后备方案：按 Enter
        _user32.PostMessageW(edit, 0x0100, 0x0D, 0)
        time.sleep(0.05)
        _user32.PostMessageW(edit, 0x0101, 0x0D, 0)
        return True, "已填入路径并按 Enter"

    @staticmethod
    def click_at_screen(x, y):
        """
        用 Win32 mouse_event 在屏幕坐标 (x, y) 上模拟真实鼠标点击。
        这会产生被 Chrome 信任的输入事件（与 JavaScript click() 不同）。
        """
        if _user32 is None:
            raise RuntimeError('屏幕坐标点击仅支持 Windows')
        _user32.SetCursorPos(int(x), int(y))
        time.sleep(0.1)
        _user32.mouse_event(0x0002, 0, 0, 0, 0)   # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.05)
        _user32.mouse_event(0x0004, 0, 0, 0, 0)   # MOUSEEVENTF_LEFTUP
        time.sleep(0.1)


# 设置 DPI 感知，确保屏幕坐标正确
if _user32 is not None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass


class PipelineTabWidget(QWidget):
    """全局流水线控制台 Tab 页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plugin_server = None
        self.storage_manager = None
        self.config_manager = None

        # 任务分配数据
        self._allocated_tasks = {}  # client_id -> [task_dicts]
        self._upload_status = {}    # client_id -> {image_name: "pending"/"uploading"/"done"/"failed"}
        self._task_status = {}      # (client_id, task_index) -> "pending"/"running"/"success"/"failed"
        self._current_project_info = None
        self._current_segments = []
        self.aliases = {}

        self.init_ui()

        # 定时刷新浏览器表
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_browser_table)
        self._refresh_timer.start(3000)

    def set_dependencies(self, plugin_server, storage_manager, config_manager):
        """注入依赖 (由 MainWindow 调用)"""
        self.plugin_server = plugin_server
        self.storage_manager = storage_manager
        self.config_manager = config_manager
        
        self._load_aliases()

        # 监听 RPC 响应
        if self.plugin_server:
            self.plugin_server.rpc_response_signal.connect(self.on_rpc_response)
            self.plugin_server.report_received_signal.connect(self.on_report_received)
            self.plugin_server.client_connected_signal.connect(lambda _: self.refresh_browser_table())
            self.plugin_server.client_disconnected_signal.connect(lambda _: self.refresh_browser_table())
            self.plugin_server.client_updated_signal.connect(lambda _: self.refresh_browser_table())

        self._populate_project_combo()
        
    def _load_aliases(self):
        if self.config_manager:
            self.aliases_file = Path(self.config_manager.workspace_dir) / "account_aliases.json"
            if self.aliases_file.exists():
                try:
                    with open(self.aliases_file, "r", encoding="utf-8") as f:
                        self.aliases = json.load(f)
                except:
                    self.aliases = {}
            else:
                self.aliases = {}

    def _save_aliases(self):
        if hasattr(self, 'aliases_file'):
            try:
                with open(self.aliases_file, "w", encoding="utf-8") as f:
                    json.dump(self.aliases, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Save aliases error: {e}")

    def init_ui(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #F5EBE6;
                font-family: "Segoe UI", "PingFang SC", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #5D4037;
                border: 1px solid #D7CCC8;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                gridline-color: #EFEBE9;
                font-size: 12px;
                color: #5D4037;
            }
            QTableWidget::item { padding: 4px; }
            QTableWidget QHeaderView::section {
                background-color: #EDE0D4;
                color: #5D4037;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 2px solid #D7CCC8;
            }
            QPushButton {
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
                color: white;
            }
            QPushButton:disabled {
                background-color: #BCAAA4;
                color: #EFEBE9;
            }
            QComboBox, QSpinBox {
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                color: #5D4037;
            }
            QLabel { font-size: 12px; color: #5D4037; }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        # ──── 标题栏 ────
        title_row = QHBoxLayout()
        title_lbl = QLabel("🚀 流水线控制台 — 分步执行")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #5D4037;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        self.btn_refresh_all = QPushButton("🔄 刷新全部")
        self.btn_refresh_all.setStyleSheet("background-color: #059669;")
        self.btn_refresh_all.clicked.connect(self._on_refresh_all)
        title_row.addWidget(self.btn_refresh_all)
        main_layout.addLayout(title_row)

        # ──── 上半部分: 浏览器表 + 设置 ────
        upper_frame = QFrame()
        upper_layout = QVBoxLayout(upper_frame)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.setSpacing(6)

        # 浏览器/账号表
        browser_grp = QGroupBox("📡 浏览器账号列表")
        browser_grp_layout = QVBoxLayout(browser_grp)

        self.browser_table = QTableWidget(0, 9)
        self.browser_table.setHorizontalHeaderLabels([
            "状态", "账号邮箱", "备注 (双击修改)", "积分", "已分配", "完成", "失败", "上传进度", "操作"
        ])
        hdr = self.browser_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col in range(3, 9):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.browser_table.setColumnWidth(0, 50)
        self.browser_table.verticalHeader().setVisible(False)
        self.browser_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.browser_table.setMaximumHeight(180)
        self.browser_table.cellChanged.connect(self._on_browser_cell_changed)
        browser_grp_layout.addWidget(self.browser_table)

        upper_layout.addWidget(browser_grp)

        # ──── 设置行 ────
        settings_row = QHBoxLayout()
        settings_row.setSpacing(12)

        settings_row.addWidget(QLabel("📂 当前项目:"))
        self.combo_project = QComboBox()
        self.combo_project.setMinimumWidth(200)
        self.combo_project.currentIndexChanged.connect(self._on_project_changed)
        settings_row.addWidget(self.combo_project)

        settings_row.addSpacing(12)
        self.chk_auto_close = QCheckBox("完成后自动关闭浏览器")
        settings_row.addWidget(self.chk_auto_close)

        settings_row.addStretch()

        self.btn_allocate = QPushButton("📊 根据积分自动分配任务")
        self.btn_allocate.setStyleSheet("background-color: #7C3AED;")
        self.btn_allocate.clicked.connect(self._on_allocate_tasks)
        settings_row.addWidget(self.btn_allocate)

        upper_layout.addLayout(settings_row)

        # ──── 三步骤按钮 ────
        step_row = QHBoxLayout()
        step_row.setSpacing(8)

        self.btn_step1 = QPushButton("📸 步骤 1: 上传图片到浏览器")
        self.btn_step1.setStyleSheet("background-color: #2563EB; padding: 10px 20px; font-size: 13px;")
        self.btn_step1.clicked.connect(self._on_step1_upload)
        self.btn_step1.setEnabled(False)
        step_row.addWidget(self.btn_step1)

        self.lbl_step1_status = QLabel("⬜ 等待分配")
        self.lbl_step1_status.setStyleSheet("font-size: 12px; color: #6B7280;")
        step_row.addWidget(self.lbl_step1_status)

        step_row.addSpacing(10)

        self.btn_step2 = QPushButton("📋 步骤 2: 下发 JSON 任务")
        self.btn_step2.setStyleSheet("background-color: #D97706; padding: 10px 20px; font-size: 13px;")
        self.btn_step2.clicked.connect(self._on_step2_send_json)
        self.btn_step2.setEnabled(False)
        step_row.addWidget(self.btn_step2)

        self.lbl_step2_status = QLabel("⬜ 等待上传")
        self.lbl_step2_status.setStyleSheet("font-size: 12px; color: #6B7280;")
        step_row.addWidget(self.lbl_step2_status)

        step_row.addSpacing(10)

        self.btn_step3 = QPushButton("▶️ 步骤 3: 开始执行")
        self.btn_step3.setStyleSheet("background-color: #059669; padding: 10px 20px; font-size: 13px;")
        self.btn_step3.clicked.connect(self._on_step3_start)
        self.btn_step3.setEnabled(False)
        step_row.addWidget(self.btn_step3)

        self.lbl_step3_status = QLabel("⬜ 等待下发")
        self.lbl_step3_status.setStyleSheet("font-size: 12px; color: #6B7280;")
        step_row.addWidget(self.lbl_step3_status)

        upper_layout.addLayout(step_row)
        main_layout.addWidget(upper_frame)

        # ──── 下半部分: 任务详情表 ────
        task_grp = QGroupBox("📋 任务分配详情")
        task_grp_layout = QVBoxLayout(task_grp)

        self.task_table = QTableWidget(0, 7)
        self.task_table.setHorizontalHeaderLabels([
            "#", "提示词 (预览)", "图片", "时长", "分配给", "上传状态", "执行状态"
        ])
        thdr = self.task_table.horizontalHeader()
        thdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        thdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in [2, 3, 4, 5, 6]:
            thdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.task_table.setColumnWidth(0, 40)
        self.task_table.verticalHeader().setVisible(False)
        task_grp_layout.addWidget(self.task_table)

        # 底部操作按钮
        footer_row = QHBoxLayout()
        self.btn_reassign = QPushButton("🔄 重新分配失败任务")
        self.btn_reassign.setStyleSheet("background-color: #7C3AED;")
        self.btn_reassign.clicked.connect(self._on_reassign_failed)
        footer_row.addWidget(self.btn_reassign)

        self.btn_stop_all = QPushButton("⏹️ 全部停止")
        self.btn_stop_all.setStyleSheet("background-color: #DC2626;")
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        footer_row.addWidget(self.btn_stop_all)

        footer_row.addStretch()

        # 日志区
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        self.log_text.setStyleSheet("background-color: #1E293B; color: #E2E8F0; font-family: 'Consolas', monospace; font-size: 11px; border-radius: 4px;")
        task_grp_layout.addLayout(footer_row)
        task_grp_layout.addWidget(self.log_text)

        main_layout.addWidget(task_grp, stretch=1)

    # ──────────────────────────────────────────
    # 日志
    # ──────────────────────────────────────────
    def _log(self, msg):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        logger.info(msg)

    # ──────────────────────────────────────────
    # 浏览器表刷新
    # ──────────────────────────────────────────
    def _on_browser_cell_changed(self, row, col):
        if col == 2:  # 备注 column
            item = self.browser_table.item(row, col)
            email_item = self.browser_table.item(row, 1)
            if item and email_item:
                email = email_item.text()
                self.aliases[email] = item.text()
                self._save_aliases()

    def refresh_browser_table(self):
        if not self.plugin_server:
            return
        
        self.browser_table.blockSignals(True) # 阻止触发 cellChanged
        clients = self.plugin_server.get_online_clients()
        self.browser_table.setRowCount(len(clients))

        for row, client in enumerate(clients):
            cid = client.get("client_id", "")
            email = client.get("email", "") or client.get("name", cid)
            pts = client.get("remaining_points", 0)
            status = client.get("status", "idle")

            # 状态图标
            status_icon = "🟢" if status in ("idle",) else ("🔵" if status == "busy" else ("🟡" if status == "low_points" else "🔴"))
            self._set_cell(row, 0, status_icon, align=Qt.AlignmentFlag.AlignCenter)

            # 邮箱
            short_email = email.split(" (W#")[0] if " (W#" in email else email
            self._set_cell(row, 1, short_email)
            
            # 备注
            alias = self.aliases.get(short_email, "")
            alias_item = QTableWidgetItem(alias)
            self.browser_table.setItem(row, 2, alias_item)

            # 积分
            pts_item = QTableWidgetItem(str(pts))
            pts_item.setForeground(QColor("#059669") if pts >= 10 else QColor("#DC2626"))
            pts_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            pts_item.setFlags(pts_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.browser_table.setItem(row, 3, pts_item)

            # 已分配 / 完成 / 失败
            allocated = self._allocated_tasks.get(cid, [])
            completed = sum(1 for k, v in self._task_status.items() if k[0] == cid and v == "success")
            failed = sum(1 for k, v in self._task_status.items() if k[0] == cid and v == "failed")
            self._set_cell(row, 4, str(len(allocated)), align=Qt.AlignmentFlag.AlignCenter)
            self._set_cell(row, 5, str(completed), align=Qt.AlignmentFlag.AlignCenter)
            self._set_cell(row, 6, str(failed), align=Qt.AlignmentFlag.AlignCenter)

            # 上传进度
            upload_info = self._upload_status.get(cid, {})
            if upload_info:
                done = sum(1 for v in upload_info.values() if v == "done")
                total = len(upload_info)
                self._set_cell(row, 7, f"{done}/{total}", align=Qt.AlignmentFlag.AlignCenter)
            else:
                self._set_cell(row, 7, "-", align=Qt.AlignmentFlag.AlignCenter)

            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(2, 2, 2, 2)
            btn_layout.setSpacing(4)

            btn_refresh = QPushButton("🔄")
            btn_refresh.setToolTip("刷新积分")
            btn_refresh.setStyleSheet("background-color: #059669; padding: 2px 6px; font-size: 11px;")
            btn_refresh.clicked.connect(lambda _, c=cid: self._refresh_single_client(c))
            btn_layout.addWidget(btn_refresh)

            btn_stop = QPushButton("⏹️")
            btn_stop.setToolTip("停止该浏览器任务")
            btn_stop.setStyleSheet("background-color: #DC2626; padding: 2px 6px; font-size: 11px;")
            btn_stop.clicked.connect(lambda _, c=cid: self._stop_single_client(c))
            btn_layout.addWidget(btn_stop)

            self.browser_table.setCellWidget(row, 8, btn_widget)
        self.browser_table.blockSignals(False)

    def _set_cell(self, row, col, text, align=Qt.AlignmentFlag.AlignLeft):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.browser_table.setItem(row, col, item)

    # ──────────────────────────────────────────
    # 项目选择
    # ──────────────────────────────────────────
    def _populate_project_combo(self):
        self.combo_project.clear()
        if not self.storage_manager:
            return
        projects = self.storage_manager.list_projects()
        self.combo_project.addItem("-- 选择项目 --", None)
        for p in projects:
            label = f"{p.get('index_str', '')} {p.get('col1', '')} - {p.get('col7', '')}"
            self.combo_project.addItem(label.strip(), p)

    def _on_project_changed(self, idx):
        p_data = self.combo_project.itemData(idx)
        self._current_project_info = p_data
        self._current_segments = []
        self._allocated_tasks.clear()
        self._upload_status.clear()
        self._task_status.clear()

        if p_data and p_data.get("path"):
            try:
                from models.project_model import ProjectModel
                proj = ProjectModel(p_data["path"])
                self._current_segments = proj.spanish_segments or []
                self._log(f"已选择项目: {p_data.get('col1', '')}，共 {len(self._current_segments)} 个片段")
            except Exception as e:
                self._log(f"⚠️ 加载项目失败: {e}")

        self._refresh_task_table()

    # ──────────────────────────────────────────
    # 任务分配
    # ──────────────────────────────────────────
    def _on_allocate_tasks(self):
        if not self._current_segments:
            QMessageBox.warning(self, "提示", "请先选择一个项目！")
            return

        if not self.plugin_server:
            QMessageBox.warning(self, "提示", "插件服务未启动！")
            return

        clients = self.plugin_server.get_online_clients()
        idle_clients = [c for c in clients if c.get("status") != "suspended"]
        if not idle_clients:
            QMessageBox.warning(self, "提示", "没有在线的浏览器 Worker！")
            return

        self._allocated_tasks.clear()
        self._upload_status.clear()
        self._task_status.clear()

        # 获取未完成的片段
        project_path = Path(self._current_project_info["path"])
        videos_dir = project_path / "downloads" / "videos"
        pending_segments = []
        for idx, seg in enumerate(self._current_segments):
            mp4_file = videos_dir / f"{idx + 1:02d}.mp4"
            if not mp4_file.exists() or mp4_file.stat().st_size == 0:
                pending_segments.append((idx, seg))

        if not pending_segments:
            QMessageBox.information(self, "提示", "所有片段的视频已完成，无需分配！")
            return

        # 积分消耗表
        for client in idle_clients:
            self._allocated_tasks[client.get("client_id", "")] = []

        worker_idx = 0
        client_ids = [c.get("client_id") for c in idle_clients]
        worker_points = {cid: next((c.get("remaining_points", 0) for c in idle_clients if c.get("client_id") == cid), 0) for cid in client_ids}

        for seg_idx, seg in pending_segments:
            duration = seg.get("duration", 6)
            if isinstance(duration, str):
                duration = int(duration.replace("s", ""))
            cost = DURATION_COST.get(duration, 10)

            assigned = False
            # Try to assign to the current worker, if not enough points, move to the next
            while worker_idx < len(client_ids):
                cid = client_ids[worker_idx]
                if worker_points[cid] >= cost:
                    worker_points[cid] -= cost
                    task = self._build_task_dict(seg_idx, seg, project_path)
                    self._allocated_tasks[cid].append(task)
                    self._task_status[(cid, seg_idx)] = "pending"
                    assigned = True
                    break
                else:
                    worker_idx += 1
            
            if not assigned:
                self._log(f"⚠️ 片段 {seg_idx+1} (需要 {cost} 积分) 无法分配，所有在线 Worker 积分均不足。")

        total_allocated = sum(len(tasks) for tasks in self._allocated_tasks.values())
        self._log(f"✅ 任务分配完成: {total_allocated}/{len(pending_segments)} 个片段已分配")

        self._refresh_task_table()
        self.refresh_browser_table()

        if total_allocated > 0:
            self.btn_step1.setEnabled(True)
            self.lbl_step1_status.setText("✅ 已分配，可以上传图片")
            self.lbl_step1_status.setStyleSheet("font-size: 12px; color: #059669; font-weight: bold;")

    def _build_task_dict(self, seg_idx, seg, project_path):
        """构建单个任务字典"""
        # 获取图片路径
        media_dir = project_path / "downloads" / "images"
        if not media_dir.exists():
            media_dir = project_path / "downloads"

        image_name = f"{seg_idx + 1:02d}.jpg"
        image_path = media_dir / image_name
        # 尝试多种扩展名
        if not image_path.exists():
            for ext in [".png", ".jpeg", ".webp"]:
                alt = media_dir / f"{seg_idx + 1:02d}{ext}"
                if alt.exists():
                    image_path = alt
                    image_name = alt.name
                    break

        # 获取提示词和时长
        prompt_text = seg.get("prompt", "") or seg.get("text", "") or seg.get("line", "")
        duration = seg.get("duration", 6)
        if isinstance(duration, str):
            duration = int(duration.replace("s", ""))

        return {
            "index": seg_idx,
            "prompt": prompt_text,
            "image_name": image_name,
            "image_path": str(image_path) if image_path.exists() else "",
            "duration": duration,
            "mode": "VIDEO_FRAMES",
            "model": "omni_1_1_flash",
            "download_path": str(project_path / "downloads" / "videos" / f"{seg_idx + 1:02d}.mp4"),
        }

    # ──────────────────────────────────────────
    # 步骤 1: 上传图片
    # ──────────────────────────────────────────
    def _on_step1_upload(self):
        if not self._allocated_tasks:
            QMessageBox.warning(self, "提示", "请先分配任务！")
            return

        self.btn_step1.setEnabled(False)
        self.btn_step1.setText("📸 正在上传图片...")
        self.lbl_step1_status.setText("🔵 上传中...")
        self.lbl_step1_status.setStyleSheet("font-size: 12px; color: #2563EB; font-weight: bold;")

        # 构建全局上传队列（跨所有 worker 串行，每次只处理一张图片）
        self._upload_queue = []
        for cid, tasks in self._allocated_tasks.items():
            self._upload_status[cid] = {}
            for idx, task in enumerate(tasks):
                img_path = task.get("image_path", "")
                img_name = task.get("image_name", "")
                if img_path and Path(img_path).exists():
                    self._upload_queue.append({
                        "client_id": cid,
                        "task_idx": idx,
                        "image_name": img_name,
                        "image_path": img_path,
                    })
                    self._upload_status[cid][img_name] = "pending"
                else:
                    self._log(f"⚠️ 跳过不存在的图片: {img_name} (路径: {img_path})")
                    self._upload_status[cid][img_name] = "skipped"

        total = len(self._upload_queue)
        self._upload_total = total
        self._upload_done_count = 0
        self._log(f"📸 开始逐张上传图片（直接 API 模式），共 {total} 张")

        # 开始处理队列中的第一个
        self._process_next_upload()

    def _process_next_upload(self):
        """处理队列中的下一个上传任务"""
        if not self._upload_queue:
            self._all_uploads_finished()
            return

        item = self._upload_queue[0]  # peek，不 pop（等确认后再 pop）
        cid = item["client_id"]
        img_name = item["image_name"]
        img_path = item["image_path"]

        self._upload_status.setdefault(cid, {})[img_name] = "uploading"
        short_email = cid.split(" (W#")[0] if " (W#" in cid else cid
        self._log(f"📤 [{self._upload_done_count + 1}/{self._upload_total}] "
                  f"上传 {img_name} → {short_email}")

        # 读取图片并转 Base64
        import base64
        p = Path(img_path)
        ext = p.suffix.lower().replace(".", "")
        if ext == "jpg":
            ext = "jpeg"
        mime = f"image/{ext}" if ext in ("png", "jpeg", "webp", "gif") else "image/png"

        try:
            with open(p, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")
            data_url = f"data:{mime};base64,{b64_str}"
        except Exception as e:
            self._log(f"❌ 读取图片失败 {img_name}: {e}")
            self._upload_status.setdefault(cid, {})[img_name] = "failed"
            self._upload_done_count += 1
            self._upload_queue.pop(0)
            QTimer.singleShot(500, self._process_next_upload)
            return

        req_id = f"upload_{cid}_{item['task_idx']}_{uuid.uuid4().hex[:6]}"
        if not hasattr(self, "_pending_uploads"):
            self._pending_uploads = {}
        self._pending_uploads[req_id] = item

        # 发送 base64 图片数据给插件，插件直接调用 Google API 上传
        self.plugin_server.send_rpc_action(
            cid, "upload_image",
            params={
                "image_name": img_name,
                "image_data_url": data_url,
                "timeout_seconds": 90,
            },
            request_id=req_id
        )

        self._refresh_task_table()
        self.refresh_browser_table()

    def _all_uploads_finished(self):
        """所有图片上传完毕"""
        self.btn_step1.setText("📸 步骤 1: 上传图片 ✅")
        self.lbl_step1_status.setText("✅ 全部上传完成")
        self.lbl_step1_status.setStyleSheet("font-size: 12px; color: #059669; font-weight: bold;")
        self.btn_step2.setEnabled(True)
        self.lbl_step2_status.setText("✅ 可以下发任务")
        self.lbl_step2_status.setStyleSheet("font-size: 12px; color: #059669; font-weight: bold;")
        self._log(f"✅ 所有图片上传完毕！({self._upload_done_count}/{self._upload_total}) 可以进行步骤 2")
        self._refresh_task_table()
        self.refresh_browser_table()

    def _run_dialog_automation(self, filepath, req_id):
        """
        在后台线程中运行 Win32 对话框自动化。
        等待文件对话框出现 → 填入路径 → 点击打开。
        """
        try:
            # 等待对话框出现并填写
            success, msg = FileDialogAutomation.fill_and_confirm(filepath, timeout=15)
            # 回到主线程处理结果
            QTimer.singleShot(0, lambda: self._on_dialog_automation_done(req_id, success, msg))
        except Exception as e:
            QTimer.singleShot(0, lambda: self._on_dialog_automation_done(req_id, False, str(e)))

    def _on_dialog_automation_done(self, req_id, success, msg):
        """对话框自动化完成后的回调（主线程）"""
        ctx = self._pending_uploads.get(req_id)
        if not ctx:
            return

        if success:
            self._log(f"📂 {msg}")
            self._log(f"   等待 Google Flow 处理上传...")
            # 不在这里 pop，等插件确认缩略图增加后再 pop
        else:
            self._log(f"❌ 桌面自动化失败: {msg}")
            # 标记失败，继续下一个
            self._pending_uploads.pop(req_id, None)
            cid = ctx["client_id"]
            img_name = ctx["image_name"]
            self._upload_status.setdefault(cid, {})[img_name] = "failed"
            self._upload_done_count += 1
            if self._upload_queue:
                self._upload_queue.pop(0)
            self._refresh_task_table()
            # 等 3 秒让可能残留的对话框关闭
            QTimer.singleShot(3000, self._process_next_upload)

    # ──────────────────────────────────────────
    # 步骤 2: 下发 JSON 任务
    # ──────────────────────────────────────────
    def _on_step2_send_json(self):
        if not self._allocated_tasks:
            return

        self.btn_step2.setEnabled(False)
        self.btn_step2.setText("📋 正在下发任务...")

        for cid, tasks in self._allocated_tasks.items():
            if not tasks:
                continue

            # 构建插件 UI 面板能理解的 JSON 格式
            json_tasks = []
            for task in tasks:
                json_task = {
                    "prompt": task.get("prompt", ""),
                    "image": task.get("image_name", ""),
                    "duration": task.get("duration", 6),
                    "mode": task.get("mode", "VIDEO_FRAMES"),
                    "model": task.get("model", "omni_1_1_flash"),
                    "download_path": task.get("download_path", ""),
                    "index": task.get("index", 0),
                }
                json_tasks.append(json_task)

            req_id = f"import_{cid}_{uuid.uuid4().hex[:6]}"
            self.plugin_server.send_rpc_action(
                cid, "import_json_tasks",
                params={
                    "json_tasks": json_tasks,
                    "auto_start": False,
                },
                request_id=req_id
            )
            self._log(f"📋 已向 {cid.split(' (W#')[0]} 下发 {len(json_tasks)} 个任务")

        self.btn_step2.setText("📋 步骤 2: 下发任务 ✅")
        self.lbl_step2_status.setText("✅ 任务已下发")
        self.lbl_step2_status.setStyleSheet("font-size: 12px; color: #059669; font-weight: bold;")
        self.btn_step3.setEnabled(True)
        self.lbl_step3_status.setText("✅ 可以开始执行")
        self.lbl_step3_status.setStyleSheet("font-size: 12px; color: #059669; font-weight: bold;")

    # ──────────────────────────────────────────
    # 步骤 3: 开始执行
    # ──────────────────────────────────────────
    def _on_step3_start(self):
        if not self._allocated_tasks:
            return

        self.btn_step3.setEnabled(False)
        self.btn_step3.setText("▶️ 执行中...")

        for cid in self._allocated_tasks.keys():
            req_id = f"start_{cid}_{uuid.uuid4().hex[:6]}"
            self.plugin_server.send_rpc_action(
                cid, "start_batch",
                params={},
                request_id=req_id
            )
            self._log(f"▶️ 已向 {cid.split(' (W#')[0]} 发送开始执行命令")
            # 更新任务状态
            for task in self._allocated_tasks.get(cid, []):
                self._task_status[(cid, task["index"])] = "running"

        self.lbl_step3_status.setText("🔵 正在执行...")
        self.lbl_step3_status.setStyleSheet("font-size: 12px; color: #2563EB; font-weight: bold;")
        self._refresh_task_table()

    # ──────────────────────────────────────────
    # RPC 响应处理
    # ──────────────────────────────────────────
    def on_rpc_response(self, response_data):
        """处理插件返回的 RPC 响应"""
        client_id = response_data.get("client_id", "")
        msg = response_data.get("message", {})
        action = msg.get("action", "")
        req_id = msg.get("request_id", "")
        success = msg.get("success", False)

        # 处理 upload_image 响应
        if action == "upload_image_response" and hasattr(self, "_pending_uploads"):
            ctx = self._pending_uploads.get(req_id)
            if not ctx:
                return

            img_name = ctx["image_name"]
            cid = ctx["client_id"]
            data = msg.get("data", {})

            if data.get("upload_success"):
                # 上传成功
                self._pending_uploads.pop(req_id, None)
                self._upload_status.setdefault(cid, {})[img_name] = "done"
                duration_ms = data.get("upload_duration_ms", 0)
                self._log(f"✅ {img_name} 上传成功！({duration_ms}ms)")
                self._upload_done_count += 1
                if self._upload_queue:
                    self._upload_queue.pop(0)
                self._refresh_task_table()
                self.refresh_browser_table()
                QTimer.singleShot(2000, self._process_next_upload)

            else:
                # 上传失败
                error = msg.get("error", data.get("error", "未知错误"))
                self._pending_uploads.pop(req_id, None)
                self._upload_status.setdefault(cid, {})[img_name] = "failed"
                self._log(f"❌ {img_name} 上传失败: {error}")
                self._upload_done_count += 1
                if self._upload_queue:
                    self._upload_queue.pop(0)
                self._refresh_task_table()
                self.refresh_browser_table()
                QTimer.singleShot(3000, self._process_next_upload)

    def on_report_received(self, report_data):
        """处理插件返回的执行报告 (video_completed / execution_report)"""
        client_id = report_data.get("client_id", "")
        data_list = report_data.get("data", [])

        for item in data_list:
            seg_idx = item.get("index")
            status = item.get("status", "")
            if seg_idx is not None:
                if status == "success":
                    self._task_status[(client_id, seg_idx)] = "success"
                    self._log(f"✅ 片段 {seg_idx + 1} 生成成功 (by {client_id.split(' (W#')[0]})")
                elif status in ("failed", "error"):
                    self._task_status[(client_id, seg_idx)] = "failed"
                    self._log(f"❌ 片段 {seg_idx + 1} 生成失败")

        self._refresh_task_table()
        self.refresh_browser_table()

    # ──────────────────────────────────────────
    # 任务详情表刷新
    # ──────────────────────────────────────────
    def _refresh_task_table(self):
        # 构建所有任务的展平列表
        all_rows = []
        for cid, tasks in self._allocated_tasks.items():
            short_email = cid.split(" (W#")[0] if " (W#" in cid else cid
            for task in tasks:
                seg_idx = task.get("index", 0)
                upload_st = self._upload_status.get(cid, {}).get(task.get("image_name", ""), "-")
                exec_st = self._task_status.get((cid, seg_idx), "pending")
                all_rows.append({
                    "idx": seg_idx,
                    "prompt": task.get("prompt", "")[:50],
                    "image": task.get("image_name", ""),
                    "duration": f"{task.get('duration', 6)}s",
                    "assigned_to": short_email,
                    "upload_status": upload_st,
                    "exec_status": exec_st,
                })

        # 也显示未分配的片段
        allocated_indices = set()
        for tasks in self._allocated_tasks.values():
            for t in tasks:
                allocated_indices.add(t.get("index", -1))

        for idx, seg in enumerate(self._current_segments):
            if idx not in allocated_indices:
                prompt_text = seg.get("prompt", "") or seg.get("text", "") or seg.get("line", "")
                all_rows.append({
                    "idx": idx,
                    "prompt": prompt_text[:50],
                    "image": f"{idx + 1:02d}.jpg",
                    "duration": f"{seg.get('duration', 6)}s" if isinstance(seg.get("duration"), int) else str(seg.get("duration", "6s")),
                    "assigned_to": "未分配",
                    "upload_status": "-",
                    "exec_status": "-",
                })

        all_rows.sort(key=lambda r: r["idx"])
        self.task_table.setRowCount(len(all_rows))

        STATUS_ICONS = {
            "pending": "⬜",
            "uploading": "🔵",
            "done": "✅",
            "failed": "❌",
            "skipped": "⏭️",
            "running": "🔵",
            "success": "✅",
            "-": "⬜",
        }

        for row, r in enumerate(all_rows):
            self._set_task_cell(row, 0, str(r["idx"] + 1), Qt.AlignmentFlag.AlignCenter)
            self._set_task_cell(row, 1, r["prompt"])
            self._set_task_cell(row, 2, r["image"], Qt.AlignmentFlag.AlignCenter)
            self._set_task_cell(row, 3, r["duration"], Qt.AlignmentFlag.AlignCenter)

            assigned_item = QTableWidgetItem(r["assigned_to"])
            if r["assigned_to"] == "未分配":
                assigned_item.setForeground(QColor("#9CA3AF"))
            else:
                assigned_item.setForeground(QColor("#2563EB"))
            assigned_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            self.task_table.setItem(row, 4, assigned_item)

            up_icon = STATUS_ICONS.get(r["upload_status"], "⬜")
            self._set_task_cell(row, 5, up_icon, Qt.AlignmentFlag.AlignCenter)

            ex_icon = STATUS_ICONS.get(r["exec_status"], "⬜")
            self._set_task_cell(row, 6, ex_icon, Qt.AlignmentFlag.AlignCenter)

    def _set_task_cell(self, row, col, text, align=Qt.AlignmentFlag.AlignLeft):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.task_table.setItem(row, col, item)

    # ──────────────────────────────────────────
    # 辅助操作
    # ──────────────────────────────────────────
    def _on_refresh_all(self):
        """刷新全部: 浏览器积分 + 项目列表"""
        if self.plugin_server:
            self.plugin_server.query_all_clients_points()
            self._log("🔄 已发送刷新积分请求")
        self._populate_project_combo()
        self.refresh_browser_table()

    def _refresh_single_client(self, client_id):
        if self.plugin_server:
            self.plugin_server.send_rpc_action(client_id, "get_points", {})
            self._log(f"🔄 刷新 {client_id.split(' (W#')[0]} 积分")

    def _stop_single_client(self, client_id):
        if self.plugin_server:
            self.plugin_server.send_rpc_action(client_id, "stop_current", {})
            self._log(f"⏹️ 已向 {client_id.split(' (W#')[0]} 发送停止命令")

    def _on_stop_all(self):
        if not self.plugin_server:
            return
        for client in self.plugin_server.get_online_clients():
            cid = client.get("client_id", "")
            self.plugin_server.send_rpc_action(cid, "stop_current", {})
        self._log("⏹️ 已向所有 Worker 发送停止命令")
        self.btn_step3.setText("▶️ 步骤 3: 开始执行")
        self.btn_step3.setEnabled(True)

    def _on_reassign_failed(self):
        """重新分配失败的任务"""
        failed_tasks = []
        for (cid, seg_idx), status in list(self._task_status.items()):
            if status == "failed":
                # 找到对应任务
                for task in self._allocated_tasks.get(cid, []):
                    if task.get("index") == seg_idx:
                        failed_tasks.append(task)
                        break
                self._task_status.pop((cid, seg_idx), None)

        if not failed_tasks:
            QMessageBox.information(self, "提示", "没有失败的任务需要重新分配。")
            return

        # 分配给有积分的空闲 worker
        clients = self.plugin_server.get_online_clients() if self.plugin_server else []
        idle_clients = [c for c in clients if c.get("status") in ("idle",) and c.get("remaining_points", 0) >= self.spin_cost.value()]

        if not idle_clients:
            QMessageBox.warning(self, "提示", "没有可用的空闲 Worker！")
            return

        wi = 0
        for task in failed_tasks:
            cid = idle_clients[wi % len(idle_clients)].get("client_id", "")
            self._allocated_tasks.setdefault(cid, []).append(task)
            self._task_status[(cid, task["index"])] = "pending"
            wi += 1

        self._log(f"🔄 已重新分配 {len(failed_tasks)} 个失败任务")
        self._refresh_task_table()
        self.refresh_browser_table()
        self.btn_step1.setEnabled(True)
