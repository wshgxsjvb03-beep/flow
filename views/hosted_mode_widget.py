# -*- coding: utf-8 -*-
"""
🤖 全局托管模式

步骤 1：刷新积分 → 标记低于阈值的浏览器 → 按「项目管理」的 50 积分批次把任务分配给浏览器
        · 批次消耗 < 小批次阈值(默认 40) 的，优先分配给「已标记的低积分浏览器」（积分必须够）
        · 其余批次分配给正常积分的浏览器（负载均衡）；低积分浏览器不会被分配大批次
步骤 2：按浏览器分组上传图片（默认每组 5 个浏览器），一组全部完成或超时后再进入下一组；
        精确记录每张失败的图片，支持「重新上传失败图片」
步骤 3：把每批任务 JSON 直接发送给对应插件并自动开始生成，实时监控每个任务成功/失败，
        视频保存在 Flow 临时下载目录，后续由用户在「批量检查视频」中核对并手动完成归位
"""
import json
import time
import shutil
import logging
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
                             QAbstractItemView, QTextEdit, QGroupBox, QSplitter)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

logger = logging.getLogger(__name__)

GREEN, RED, YELLOW, BLUE, GRAY = "#DCFCE7", "#FEE2E2", "#FEF9C3", "#DBEAFE", "#F3F4F6"


class HostedModeWidget(QWidget):
    def __init__(self, plugin_server, main_window, parent=None):
        super().__init__(parent)
        self.plugin_server = plugin_server
        self.mw = main_window
        self.settings_file = Path(main_window.workspace_dir) / "hosted_mode.json"
        self.aliases_file = Path(main_window.workspace_dir) / "account_aliases.json"
        self.aliases = {}
        self._load_aliases()

        # 设置
        self.threshold = 50
        self.small_threshold = 40
        self.group_size = 5
        self.upload_timeout = 60
        self._load_settings()

        # 精准关闭管理
        self._pending_closes = {}
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(400)
        self._close_timer.timeout.connect(self._poll_pending_closes)

        # 运行数据
        self.batches = []            # list[dict]
        self.plan = {}               # cid -> {"cid","email","label","points","low","remaining","batch_ids":[]}
        self.upload_queue = []       # 待上传的浏览器分组
        self.upload_pending = {}     # request_id -> {"cid","paths"}
        self.upload_group_deadline = 0
        self.upload_group_active = False
        self.upload_retry_only = False
        self.running = False         # 步骤 3 是否在运行

        self._init_ui()

        self.upload_timer = QTimer(self)
        self.upload_timer.setInterval(500)
        self.upload_timer.timeout.connect(self._upload_tick)

        if self.plugin_server:
            self.plugin_server.client_connected_signal.connect(self._schedule_refresh)
            self.plugin_server.client_updated_signal.connect(self._schedule_refresh)
            self.plugin_server.client_disconnected_signal.connect(self._on_client_disconnected)
            self.plugin_server.rpc_response_signal.connect(self._on_rpc_response)
            self.plugin_server.hosted_event_signal.connect(self._on_hosted_event)
        self._refresh_pending = False
        self.refresh_all()

    # ──────────────────────────────── 设置持久化
    def _load_aliases(self):
        try:
            if self.aliases_file.exists():
                self.aliases = json.loads(self.aliases_file.read_text(encoding="utf-8"))
            else:
                self.aliases = {}
        except Exception as e:
            logger.warning(f"读取账号备注失败: {e}")
            self.aliases = {}

    def _load_settings(self):
        try:
            if self.settings_file.exists():
                d = json.loads(self.settings_file.read_text(encoding="utf-8"))
                self.threshold = int(d.get("threshold", 50))
                self.small_threshold = int(d.get("small_threshold", 40))
                self.group_size = int(d.get("group_size", 5))
                self.upload_timeout = int(d.get("upload_timeout", 60))
        except Exception as e:
            logger.warning(f"读取托管设置失败: {e}")

    def _save_settings(self):
        self.threshold = self.spin_threshold.value()
        self.small_threshold = self.spin_small.value()
        self.group_size = self.spin_group.value()
        self.upload_timeout = self.spin_timeout.value()
        try:
            self.settings_file.write_text(json.dumps({
                "threshold": self.threshold, "small_threshold": self.small_threshold,
                "group_size": self.group_size, "upload_timeout": self.upload_timeout}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存托管设置失败: {e}")
        self.refresh_all()

    # ──────────────────────────────── UI
    @staticmethod
    def _btn(text, color, hover):
        b = QPushButton(text)
        b.setStyleSheet(f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; padding: 7px 14px; border-radius: 4px; }}"
                        f"QPushButton:hover {{ background-color: {hover}; }} QPushButton:disabled {{ background-color: #9CA3AF; }}")
        return b

    def _spin(self, lo, hi, val, suffix):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setSuffix(suffix)
        s.setStyleSheet("padding: 3px; font-size: 13px;")
        s.valueChanged.connect(lambda _: self._save_settings())
        return s

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 步骤 1
        g1 = QGroupBox("步骤 1：刷新积分 · 标记低积分浏览器 · 按批次分配任务")
        l1 = QVBoxLayout(g1)
        r = QHBoxLayout()
        self.btn_refresh = self._btn("🔄 刷新积分", "#059669", "#047857")
        self.btn_refresh.clicked.connect(self.on_refresh_points)
        r.addWidget(self.btn_refresh)
        r.addWidget(QLabel("低积分阈值："))
        self.spin_threshold = self._spin(0, 100000, self.threshold, " 积分")
        r.addWidget(self.spin_threshold)
        r.addWidget(QLabel("小批次（低于）："))
        self.spin_small = self._spin(1, 100000, self.small_threshold, " 积分")
        r.addWidget(self.spin_small)
        self.btn_close_marked = self._btn("🔴 关闭已标记的低积分浏览器", "#DC2626", "#B91C1C")
        self.btn_close_marked.clicked.connect(self.on_close_marked)
        r.addWidget(self.btn_close_marked)
        r.addStretch()
        self.lbl_conn = QLabel("")
        r.addWidget(self.lbl_conn)
        l1.addLayout(r)

        r = QHBoxLayout()
        self.btn_alloc_current = self._btn("📌 分配当前项目", "#2563EB", "#1D4ED8")
        self.btn_alloc_current.setToolTip("只分配「项目管理」中当前打开的项目")
        self.btn_alloc_current.clicked.connect(lambda: self.on_allocate(all_projects=False))
        r.addWidget(self.btn_alloc_current)
        self.btn_alloc_all = self._btn("📚 分配所有勾选的项目", "#7C3AED", "#6D28D9")
        self.btn_alloc_all.setToolTip("分配「项目管理」左侧列表中所有打勾的项目")
        self.btn_alloc_all.clicked.connect(lambda: self.on_allocate(all_projects=True))
        r.addWidget(self.btn_alloc_all)
        self.btn_clear_plan = self._btn("🧹 清空分配", "#6B7280", "#4B5563")
        self.btn_clear_plan.clicked.connect(self.on_clear_plan)
        r.addWidget(self.btn_clear_plan)

        r.addSpacing(15)
        self.btn_clear_media = self._btn("🗑️ 清空Flow媒体", "#475569", "#334155")
        self.btn_clear_media.setToolTip("在所有已连接浏览器中，删除当前 Flow 页面上的全部图片和视频（移入回收站）")
        self.btn_clear_media.clicked.connect(self.on_clear_media_clicked)
        r.addWidget(self.btn_clear_media)

        self.btn_clear_tasks = self._btn("🧹 清空插件任务", "#475569", "#334155")
        self.btn_clear_tasks.setToolTip("清空所有已连接浏览器插件中的全部任务列表")
        self.btn_clear_tasks.clicked.connect(self.on_clear_tasks_clicked)
        r.addWidget(self.btn_clear_tasks)

        r.addStretch()
        self.lbl_summary = QLabel("")
        r.addWidget(self.lbl_summary)
        l1.addLayout(r)
        root.addWidget(g1)

        # 步骤 2 / 3
        g2 = QGroupBox("步骤 2：分组上传图片    ·    步骤 3：发送任务并开始生成")
        l2 = QHBoxLayout(g2)
        l2.addWidget(QLabel("每组浏览器数："))
        self.spin_group = self._spin(1, 50, self.group_size, " 个")
        l2.addWidget(self.spin_group)
        l2.addWidget(QLabel("单组超时："))
        self.spin_timeout = self._spin(15, 600, self.upload_timeout, " 秒")
        l2.addWidget(self.spin_timeout)
        self.btn_upload = self._btn("📤 步骤2：开始上传图片", "#0891B2", "#0E7490")
        self.btn_upload.clicked.connect(lambda: self.start_upload(retry_only=False))
        l2.addWidget(self.btn_upload)
        self.btn_reupload = self._btn("🔁 重新上传失败图片", "#EA580C", "#C2410C")
        self.btn_reupload.clicked.connect(lambda: self.start_upload(retry_only=True))
        l2.addWidget(self.btn_reupload)
        self.btn_flip_failed = self._btn("↔️ 一键翻转失败图片", "#0D9488", "#0F766E")
        self.btn_flip_failed.setToolTip("将所有上传失败的图片进行左右翻转，用新图片替换并删除原图（保留原文件名）")
        self.btn_flip_failed.clicked.connect(self.flip_failed_upload_images)
        l2.addWidget(self.btn_flip_failed)
        l2.addSpacing(20)
        self.btn_run = self._btn("🚀 步骤3：发送任务并开始生成", "#16A34A", "#15803D")
        self.btn_run.clicked.connect(self.start_run)
        l2.addWidget(self.btn_run)
        self.btn_stop = self._btn("⏹ 停止", "#DC2626", "#B91C1C")
        self.btn_stop.clicked.connect(self.stop_run)
        l2.addWidget(self.btn_stop)
        l2.addStretch()
        root.addWidget(g2)

        # 表格
        split = QSplitter(Qt.Orientation.Vertical)
        self.tbl_browsers = QTableWidget(0, 7)
        self.tbl_browsers.setHorizontalHeaderLabels(["状态标记", "账号", "备注", "积分", "分配批次", "计划消耗 / 剩余", "进度"])
        self._setup_table(self.tbl_browsers, stretch_cols=(1, 4, 6))
        split.addWidget(self.tbl_browsers)

        self.tbl_batches = QTableWidget(0, 7)
        self.tbl_batches.setHorizontalHeaderLabels(["项目", "批次", "分镜序号", "积分", "分配浏览器", "图片上传", "生成结果"])
        self._setup_table(self.tbl_batches, stretch_cols=(0, 4, 5, 6))
        split.addWidget(self.tbl_batches)
        split.setSizes([220, 320])
        root.addWidget(split, stretch=1)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(130)
        self.log_text.setStyleSheet("background-color: #1E293B; color: #E2E8F0; font-family: Consolas, monospace; font-size: 11px; border-radius: 4px;")
        root.addWidget(self.log_text)

    @staticmethod
    def _setup_table(t, stretch_cols):
        hdr = t.horizontalHeader()
        for c in range(t.columnCount()):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c in stretch_cols
                                     else QHeaderView.ResizeMode.ResizeToContents)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setStyleSheet("QTableWidget { background-color: white; border: 1px solid #D7CCC8; border-radius: 4px; font-size: 12px; color: #5D4037; }"
                        "QHeaderView::section { background-color: #EDE0D4; color: #5D4037; font-weight: bold; padding: 5px; border: none; }")

    def _log(self, msg):
        self.log_text.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        logger.info(f"[Hosted] {msg}")

    # ──────────────────────────────── 浏览器信息
    def _clients(self):
        try:
            return self.plugin_server.get_online_clients() if self.plugin_server else []
        except Exception:
            return []

    @staticmethod
    def _email(c):
        e = c.get("email") or ""
        if e:
            return e
        cid = c.get("client_id", "")
        return cid.split(" (W#")[0] if " (W#" in cid else cid

    def _alias(self, email):
        return self.aliases.get(email, "")

    def _label(self, email):
        a = self._alias(email)
        return f"{email}（{a}）" if a else email

    def _is_low(self, c):
        return bool(c.get("points_known")) and int(c.get("remaining_points", 0)) < self.threshold

    def _resolve_client(self, entry):
        """按 client_id 找在线浏览器；页面刷新导致 id 变化时按唯一邮箱重新绑定。"""
        clients = self._clients()
        for c in clients:
            if c.get("client_id") == entry["cid"]:
                return c
        if entry.get("email"):
            m = [c for c in clients if c.get("email") == entry["email"]]
            if len(m) == 1:
                old = entry["cid"]
                entry["cid"] = m[0]["client_id"]
                if old in self.plan and old != entry["cid"]:
                    self.plan[entry["cid"]] = self.plan.pop(old)
                    for b in self.batches:
                        if b.get("cid") == old:
                            b["cid"] = entry["cid"]
                return m[0]
        return None

    # ──────────────────────────────── 刷新 UI
    def _schedule_refresh(self, *a):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(250, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = False
        self.refresh_all()

    def refresh_all(self):
        self._load_aliases()
        self._refresh_browsers()
        self._refresh_batches()

    def _refresh_browsers(self):
        clients = self._clients()
        low = sum(1 for c in clients if self._is_low(c))
        self.lbl_conn.setText(f"在线浏览器 {len(clients)} 个 | 已标记低积分 {low} 个")

        rows = list(clients)
        online_ids = {c.get("client_id") for c in clients}
        offline = [e for cid, e in self.plan.items() if cid not in online_ids]
        self.tbl_browsers.setRowCount(len(rows) + len(offline))
        for i, c in enumerate(rows):
            cid = c.get("client_id")
            email = self._email(c)
            known = bool(c.get("points_known"))
            pts = int(c.get("remaining_points", 0)) if known else None
            entry = self.plan.get(cid)
            if not known:
                mark, color = "⚪ 未读取积分", GRAY
            elif self._is_low(c):
                mark, color = "🔴 低积分（已标记）", RED
            else:
                mark, color = "🟢 正常", None
            if c.get("bg_ok") is False:
                mark, color = mark + " | ⚠️插件后台未更新", YELLOW
            elif "bg_ok" not in c:
                mark = mark + " | ❔后台版本未知"
            self._put(self.tbl_browsers, i, 0, mark, color)
            self._put(self.tbl_browsers, i, 1, email or "(未识别账号)", color, tip=cid)
            self._put(self.tbl_browsers, i, 2, self._alias(email), color)
            self._put(self.tbl_browsers, i, 3, "-" if pts is None else str(pts), color, center=True)
            if entry:
                bl = [b for b in self.batches if b["id"] in entry["batch_ids"]]
                self._put(self.tbl_browsers, i, 4, "、".join(b["short"] for b in bl), color)
                planned = sum(b["points"] for b in bl)
                self._put(self.tbl_browsers, i, 5, f"{planned} / {(pts or 0) - planned}", color, center=True)
                self._put(self.tbl_browsers, i, 6, self._browser_progress(bl), color)
            else:
                for col in (4, 5, 6):
                    self._put(self.tbl_browsers, i, col, "", color)
        for j, e in enumerate(offline):
            i = len(rows) + j
            self._put(self.tbl_browsers, i, 0, "⚫ 已断开", GRAY)
            self._put(self.tbl_browsers, i, 1, e["email"], GRAY)
            self._put(self.tbl_browsers, i, 2, self._alias(e["email"]), GRAY)
            self._put(self.tbl_browsers, i, 3, str(e.get("points", "-")), GRAY, center=True)
            bl = [b for b in self.batches if b["id"] in e["batch_ids"]]
            self._put(self.tbl_browsers, i, 4, "、".join(b["short"] for b in bl), GRAY)
            self._put(self.tbl_browsers, i, 5, "", GRAY)
            self._put(self.tbl_browsers, i, 6, self._browser_progress(bl), GRAY)

    @staticmethod
    def _browser_progress(bl):
        if not bl:
            return ""
        up_ok = sum(1 for b in bl if b["upload_state"] == "成功")
        done = sum(1 for b in bl if b["run_state"] == "完成")
        ok = sum(b["ok"] for b in bl)
        fail = sum(b["fail"] for b in bl)
        return f"上传 {up_ok}/{len(bl)} 批 | 生成完成 {done}/{len(bl)} 批 | ✅{ok} ❌{fail}"

    def _refresh_batches(self):
        self.tbl_batches.setRowCount(len(self.batches))
        total_pts = sum(b["points"] for b in self.batches)
        unassigned = [b for b in self.batches if not b.get("cid")]
        self.lbl_summary.setText(
            f"共 {len(self.batches)} 批 · {total_pts} 积分" + (f" · ⚠️ 未分配 {len(unassigned)} 批" if unassigned else ""))
        for i, b in enumerate(self.batches):
            self._put(self.tbl_batches, i, 0, b["project_label"], tip=b["project_path"])
            self._put(self.tbl_batches, i, 1, f"第 {b['batch_no']} 批", center=True)
            self._put(self.tbl_batches, i, 2, ", ".join(str(x + 1) for x in b["seg_indices"]))
            small = b["points"] < self.small_threshold
            self._put(self.tbl_batches, i, 3, f"{b['points']}" + (" (小)" if small else ""), center=True)
            if b.get("cid"):
                self._put(self.tbl_batches, i, 4, self._label(b["email"]) + ("  [低积分号]" if b.get("to_low") else ""))
            else:
                self._put(self.tbl_batches, i, 4, "⚠️ 未分配（没有积分足够的浏览器）", YELLOW)

            # 上传
            st = b["upload_state"]
            fails = b["upload_failed"]
            if st == "成功":
                txt, col = f"✅ 成功 {len(b['images'])}/{len(b['images'])}", GREEN
            elif st == "失败":
                names = "、".join(Path(p).name for p in fails)
                txt, col = f"❌ 失败 {len(fails)} 张：{names}", RED
            elif st == "上传中":
                txt, col = "⏳ 上传中...", BLUE
            else:
                txt, col = f"未上传（{len(b['images'])} 张）", None
            tip = "\n".join(f"{Path(p).name}: {r}" for p, r in fails.items()) if fails else "\n".join(b["images"])
            self._put(self.tbl_batches, i, 5, txt, col, tip=tip)

            # 生成
            rs = b["run_state"]
            n = len(b["tasks"])
            col = {"完成": GREEN if b["fail"] == 0 else YELLOW, "生成中": BLUE, "已发送": BLUE,
                   "发送失败": RED, "连接断开": RED}.get(rs)
            txt = rs
            if rs in ("生成中", "完成", "连接断开", "已发送"):
                txt = f"{rs} | ✅{b['ok']} ❌{b['fail']} / {n}"
            fail_tip = "\n".join(f"{Path(k).name}: {v}" for k, v in b["fail_msgs"].items())
            self._put(self.tbl_batches, i, 6, txt, col, tip=fail_tip or None)

    def _put(self, table, row, col, text, color=None, center=False, tip=None):
        it = QTableWidgetItem(str(text))
        if center:
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            it.setBackground(QColor(color))
        if tip:
            it.setToolTip(str(tip))
        table.setItem(row, col, it)

    # ──────────────────────────────── 步骤 1
    def on_refresh_points(self):
        if not self._clients():
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。请打开 Google Flow 项目页面。")
            return
        n = self.plugin_server.query_all_clients_points()
        self._log(f"已向 {n} 个浏览器发送读取积分指令...")
        self.btn_refresh.setEnabled(False)
        QTimer.singleShot(5000, lambda: (self.btn_refresh.setEnabled(True), self.refresh_all(), self._log_marks()))

    def _log_marks(self):
        low = [c for c in self._clients() if self._is_low(c)]
        unk = [c for c in self._clients() if not c.get("points_known")]
        if low:
            self._log(f"🔴 已标记 {len(low)} 个低于 {self.threshold} 积分的浏览器（分配时只会分给它们小批次）："
                      + "、".join(f"{self._label(self._email(c))}={c.get('remaining_points')}" for c in low))
        if unk:
            self._log(f"⚪ {len(unk)} 个浏览器未读取到积分，分配时会被跳过")

    def on_close_marked(self):
        low = [c for c in self._clients() if self._is_low(c)]
        if not low:
            QMessageBox.information(self, "提示", f"没有积分低于 {self.threshold} 的浏览器（请先刷新积分）。")
            return
        busy_cids = {c["client_id"] for c in low if c.get("client_id") in self.plan and self.plan[c["client_id"]]["batch_ids"]}
        items = []
        for c in low:
            cid = c.get("client_id")
            email = self._email(c)
            items.append({
                "client": c,
                "client_id": cid,
                "label": self._label(email),
                "points": c.get("remaining_points", 0),
                "is_busy": cid in busy_cids,
            })

        from views.close_confirm_dialog import CloseConfirmDialog
        from PyQt6.QtWidgets import QDialog
        dlg = CloseConfirmDialog(
            self,
            title="确认关闭低积分浏览器",
            header_text=f"将关闭以下 {len(low)} 个低积分浏览器（阈值：<{self.threshold} 积分）：",
            items=items,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.get_selected_clients()
        if not selected:
            return

        for c in selected:
            email = self._email(c)
            self._request_close(c["client_id"], f"{self._label(email)}（{c.get('remaining_points')} 积分）", email)
        self._log(f"已发送关闭指令给 {len(selected)} 个低积分浏览器")

    def _busy(self):
        return self.running or self.upload_group_active or bool(self.upload_queue)

    def on_clear_plan(self):
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请先停止。")
            return
        self.batches, self.plan = [], {}
        self.refresh_all()
        self._log("已清空分配")

    # ──────────────────────────────────────────
    # 批量清空：Flow 媒体 / 插件任务
    # ──────────────────────────────────────────
    def _label_for_client_id(self, client_id):
        for c in self._clients():
            if c.get("client_id") == client_id:
                return self._label(self._email(c))
        return client_id.split(" (W#")[0]

    def _broadcast(self, action, what):
        clients = self._clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        sent = 0
        for c in clients:
            if self.plugin_server.send_rpc_action(c.get("client_id"), action, {}):
                sent += 1
        self._log(f"⏳ 已向 {sent} 个浏览器发送「{what}」指令...")

    def on_clear_media_clicked(self):
        n = len(self._clients())
        if not n:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        reply = QMessageBox.warning(
            self, "确认清空 Flow 媒体",
            f"将在 {n} 个浏览器当前打开的 Flow 项目中，删除页面上的【所有图片和视频】。\n\n"
            "（相当于在每个 Flow 页面按 Ctrl+A 再按 Delete，删除的内容会进入 Flow 回收站）\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._broadcast("clear_media", "清空 Flow 媒体")

    def on_clear_tasks_clicked(self):
        n = len(self._clients())
        if not n:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        reply = QMessageBox.question(
            self, "确认清空插件任务",
            f"将清空 {n} 个浏览器插件中的【全部任务列表】。\n\n（Flow 云端项目和已下载文件不受影响）\n\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._broadcast("clear_tasks", "清空插件任务")

    # ──────────────────────────────────────────
    # 关闭浏览器（定位该账号的 Chrome 窗口 → 精准关闭）
    # ──────────────────────────────────────────
    def _request_close(self, client_id, label, email=""):
        self._log(f"⚡ 正在向插件发送精准关闭指令: {label}")
        import uuid
        token = "FLOWCLOSE-" + uuid.uuid4().hex[:10]
        self.plugin_server.close_client_browser(client_id, token)

        if not hasattr(self, "_pending_closes"):
            self._pending_closes = {}
            self._close_timer = QTimer(self)
            self._close_timer.setInterval(400)
            self._close_timer.timeout.connect(self._poll_pending_closes)
        self._pending_closes[token] = {"label": label, "client_id": client_id, "email": email,
                                       "start": time.time(), "hwnds": None, "closed_at": None, "retried": False}
        if not self._close_timer.isActive():
            self._close_timer.start()

    def _client_connected(self, client_id):
        return any(c.get("client_id") == client_id for c in self._clients())

    def _poll_pending_closes(self):
        from services import browser_closer as bc
        now = time.time()
        for token, p in list(self._pending_closes.items()):
            try:
                if not self._client_connected(p["client_id"]):
                    self._log(f"✅ 浏览器已成功关闭: {p['label']}")
                    del self._pending_closes[token]
                    continue

                if p["hwnds"] is None:
                    hwnds, profile_dir, profile_email = bc.find_windows_for_email(p["email"])
                    where = f"Chrome 用户「{profile_dir}」({profile_email})" if hwnds else ""
                    if not hwnds:
                        hwnds = bc.find_windows_by_title_token(token)
                        where = "标题标记窗口" if hwnds else ""
                    if hwnds:
                        for h in hwnds:
                            bc.close_window(h)
                        p["hwnds"] = hwnds
                        p["closed_at"] = now
                        self._log(f"🪟 找到 {where} 的 {len(hwnds)} 个窗口，正在使用强制命令关闭: {p['label']}")
                    elif now - p["start"] > 6:
                        self._log(f"❌ 未找到该账号的浏览器窗口，且插件尝试自动关闭失败: {p['label']}")
                        del self._pending_closes[token]
                else:
                    remaining = [h for h in p["hwnds"] if bc.window_exists(h)]
                    if not remaining:
                        self._log(f"✅ 浏览器已关闭: {p['label']}")
                        del self._pending_closes[token]
                    elif not p["retried"] and now - p["closed_at"] > 4:
                        for h in remaining:
                            bc.close_window(h)
                        p["retried"] = True
                        p["closed_at"] = now
                    elif p["retried"] and now - p["closed_at"] > 5:
                        self._log(f"❌ 窗口未能关闭（可能弹出了“确定离开”提示，请手动处理）: {p['label']}")
                        del self._pending_closes[token]
            except Exception as e:
                self._log(f"❌ 关闭出错: {p['label']} - {e}")
                self._pending_closes.pop(token, None)
        if not self._pending_closes:
            self._close_timer.stop()

    def _points_of(self, task):
        cm = getattr(self.mw, "config_manager", None)
        d = task.get("duration", 6)
        if cm:
            return cm.get_points_for_duration(d)
        return {10: 15, 8: 12, 6: 10, 4: 7}.get(d, 7)

    def _collect_project_batches(self, all_projects):
        """调用项目管理同一套拆批逻辑，返回 (批次列表, 错误列表)。"""
        detail = self.mw.detail_widget
        prev = detail.project_path
        if all_projects:
            items = []
            lst = self.mw.list_projects
            for i in range(lst.count()):
                it = lst.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    items.append((it.data(Qt.ItemDataRole.UserRole), it.text().replace("●", "").strip()))
        else:
            if not prev:
                return [], ["请先在「项目管理」中打开一个项目"]
            cur = self.mw.list_projects.currentItem()
            items = [(str(prev), cur.text().replace("●", "").strip() if cur else Path(prev).name)]

        result, errors = [], []
        try:
            for path, label in items:
                if not path:
                    continue
                if not detail.project_path or str(detail.project_path) != str(path):
                    detail.set_project(path)
                res = detail.build_batches()
                if res.get("error"):
                    if res.get("level") != "info":
                        errors.append(f"{label}：{res['error']}")
                    continue
                for n, batch in enumerate(res["batches"], start=1):
                    tasks, images, segs = [], [], []
                    for t in batch:
                        segs.append(t.get("_original_index", 0))
                        clean = {k: v for k, v in t.items() if not k.startswith("_")}
                        tasks.append(clean)
                        for key in ("local_image_path", "end_local_image_path"):
                            p = clean.get(key)
                            if p and p not in images:
                                images.append(p)
                    pts = sum(self._points_of(t) for t in tasks)
                    pid = Path(path).name
                    result.append({
                        "id": f"{pid}#B{n}", "short": f"{label.split()[0] if label else pid}-第{n}批",
                        "project_path": str(path), "project_label": label, "batch_no": n,
                        "tasks": tasks, "seg_indices": segs, "images": images, "points": pts,
                        "cid": None, "email": "", "to_low": False,
                        "upload_state": "未上传", "upload_failed": {},
                        "run_state": "未开始", "ok": 0, "fail": 0, "done_paths": set(), "fail_msgs": {},
                    })
        finally:
            if prev and (not detail.project_path or str(detail.project_path) != str(prev)):
                detail.set_project(prev)
        return result, errors

    def on_allocate(self, all_projects):
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请先停止后再重新分配。")
            return
        clients = self._clients()
        if not clients:
            QMessageBox.information(self, "提示", "当前没有已连接的浏览器。")
            return
        known = [c for c in clients if c.get("points_known")]
        if not known:
            QMessageBox.information(self, "提示", "还没有读取到任何浏览器的积分，请先点击「刷新积分」。")
            return

        batches, errors = self._collect_project_batches(all_projects)
        if errors:
            self._log("⚠️ 以下项目未能拆批：\n  " + "\n  ".join(errors))
        if not batches:
            QMessageBox.information(self, "提示", "没有需要生成的批次。\n\n" + ("\n".join(errors[:8]) if errors else "所有分句都已生成。"))
            return

        # —— 分配算法 ——
        cap = {c["client_id"]: int(c.get("remaining_points", 0)) for c in known}
        low_ids = [c["client_id"] for c in known if self._is_low(c)]
        normal_ids = [c["client_id"] for c in known if not self._is_low(c)]
        count = {cid: 0 for cid in cap}
        by_id = {c["client_id"]: c for c in known}
        self.plan = {}

        def assign(b, cid, to_low):
            cap[cid] -= b["points"]
            count[cid] += 1
            c = by_id[cid]
            b["cid"], b["email"], b["to_low"] = cid, self._email(c), to_low
            e = self.plan.setdefault(cid, {"cid": cid, "email": self._email(c), "points": int(c.get("remaining_points", 0)),
                                           "low": to_low, "batch_ids": []})
            e["batch_ids"].append(b["id"])

        leftover = []
        # ① 小批次 → 低积分浏览器（最佳适配：剩余积分最少但够用的）
        for b in sorted([b for b in batches if b["points"] < self.small_threshold], key=lambda x: -x["points"]):
            cands = [cid for cid in low_ids if cap[cid] >= b["points"]]
            if cands:
                assign(b, min(cands, key=lambda cid: cap[cid]), True)
            else:
                leftover.append(b)
        # ② 其余批次 → 正常积分浏览器（负载均衡：分得最少的优先，其次剩余积分多的）
        rest = [b for b in batches if b["points"] >= self.small_threshold] + leftover
        for b in sorted(rest, key=lambda x: -x["points"]):
            cands = [cid for cid in normal_ids if cap[cid] >= b["points"]]
            if cands:
                assign(b, min(cands, key=lambda cid: (count[cid], -cap[cid])), False)

        # 保持项目/批次顺序展示
        self.batches = batches
        un = [b for b in batches if not b["cid"]]
        self._log(f"✅ 分配完成：{len(batches)} 批，已分配 {len(batches) - len(un)} 批，"
                  f"涉及 {len(self.plan)} 个浏览器" + (f"；⚠️ {len(un)} 批因积分不足未分配" if un else ""))
        for b in batches:
            if b["cid"]:
                self._log(f"   {b['short']}（{b['points']} 积分）→ {self._label(b['email'])}" + (" [低积分号]" if b["to_low"] else ""))
        self.refresh_all()

    # ──────────────────────────────── 步骤 2：分组上传
    def start_upload(self, retry_only):
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请稍候。")
            return
        if not self.plan:
            QMessageBox.information(self, "提示", "请先完成步骤 1 的任务分配。")
            return
        jobs = []   # [(entry, paths)]
        missing_local = 0
        for cid, entry in self.plan.items():
            paths = []
            for b in self.batches:
                if b["id"] not in entry["batch_ids"] or b["run_state"] in ("完成", "生成中", "已发送"):
                    continue
                if retry_only:
                    if b["upload_state"] != "失败":
                        continue
                    targets = list(b["upload_failed"].keys())
                else:
                    if b["upload_state"] == "成功":
                        continue
                    targets = b["images"]
                    if not targets:
                        b["upload_state"] = "成功"
                        continue
                # 本地文件不存在的直接判失败
                ok_targets = []
                for p in targets:
                    if Path(p).exists():
                        ok_targets.append(p)
                    else:
                        b["upload_failed"][p] = "本地文件不存在"
                        b["upload_state"] = "失败"
                        missing_local += 1
                for p in ok_targets:
                    if p not in paths:
                        paths.append(p)
                if ok_targets:
                    b["upload_state"] = "上传中"
            if paths:
                jobs.append((entry, paths))
        if missing_local:
            self._log(f"❌ {missing_local} 张图片在本地不存在，已标记为失败")
        if not jobs:
            self.refresh_all()
            QMessageBox.information(self, "提示", "没有需要上传的图片。" if not retry_only else "没有上传失败的图片。")
            return

        g = self.spin_group.value()
        self.upload_queue = [jobs[i:i + g] for i in range(0, len(jobs), g)]
        self._log(f"📤 开始上传：{len(jobs)} 个浏览器，分 {len(self.upload_queue)} 组（每组 {g} 个）")
        self.refresh_all()
        self._start_next_group()
        self.upload_timer.start()

    def _start_next_group(self):
        self.upload_pending = {}
        if not self.upload_queue:
            self.upload_group_active = False
            self.upload_timer.stop()
            self._finish_upload_summary()
            return
        group = self.upload_queue.pop(0)
        timeout = self.spin_timeout.value()
        max_imgs = 0
        for entry, paths in group:
            c = self._resolve_client(entry)
            if not c:
                self._mark_upload_result(entry, [], paths, {p: "浏览器未连接" for p in paths})
                continue
            req = self.plugin_server.send_rpc_action(c["client_id"], "upload_images",
                                                     {"paths": paths, "timeout_seconds": timeout})
            if req:
                self.upload_pending[req] = {"entry": entry, "paths": paths}
                max_imgs = max(max_imgs, len(paths))
                self._log(f"   → {self._label(entry['email'])}：上传 {len(paths)} 张")
            else:
                self._mark_upload_result(entry, [], paths, {p: "发送上传指令失败" for p in paths})
        self.upload_group_active = True
        # 插件端确认超时 = timeout；这里额外留出拖放耗时（每 10 张约 2 秒）+ 余量
        self.upload_group_deadline = time.time() + timeout + 3 * ((max_imgs + 9) // 10) + 10
        if not self.upload_pending:
            QTimer.singleShot(0, self._start_next_group)
        self.refresh_all()

    def _upload_tick(self):
        if not self.upload_group_active:
            return
        if not self.upload_pending:
            self._start_next_group()
            return
        if time.time() > self.upload_group_deadline:
            for req, job in list(self.upload_pending.items()):
                self._log(f"⏱️ {self._label(job['entry']['email'])} 上传超时，强制进入下一组")
                self._mark_upload_result(job["entry"], [], job["paths"], {p: "上传超时（浏览器无响应）" for p in job["paths"]})
            self.upload_pending = {}
            self._start_next_group()

    def _mark_upload_result(self, entry, ok_paths, failed_paths, errors):
        ok_set = set(ok_paths)
        for b in self.batches:
            if b["id"] not in entry["batch_ids"]:
                continue
            touched = False
            for p in b["images"]:
                if p in ok_set:
                    b["upload_failed"].pop(p, None)
                    touched = True
                elif p in failed_paths:
                    b["upload_failed"][p] = errors.get(p) or errors.get("_all") or "上传失败"
                    touched = True
            if touched or b["upload_state"] == "上传中":
                b["upload_state"] = "失败" if b["upload_failed"] else "成功"
        self.refresh_all()

    def _finish_upload_summary(self):
        ok = sum(1 for b in self.batches if b["upload_state"] == "成功")
        bad = [b for b in self.batches if b["upload_state"] == "失败"]
        self._log(f"📤 上传结束：{ok} 批成功，{len(bad)} 批有失败图片" + ("（可点击「↔️ 一键翻转失败图片」或「🔁 重新上传失败图片」）" if bad else ""))
        for b in bad:
            self._log(f"   ❌ {b['short']}：" + "；".join(f"{Path(p).name}({r})" for p, r in b["upload_failed"].items()))
        self.refresh_all()

    def flip_failed_upload_images(self):
        """
        一键将所有上传失败的图片进行左右翻转：
        生成翻转后的新图片替换原来的老图片，继承原图片名称，并删除原图片文件。
        """
        if self._busy():
            QMessageBox.warning(self, "提示", "正在上传或生成中，请先停止后再翻转图片。")
            return

        failed_paths = []
        for b in self.batches:
            for p in (b.get("upload_failed") or {}).keys():
                if p and p not in failed_paths:
                    failed_paths.append(p)

        if not failed_paths:
            QMessageBox.information(self, "提示", "当前没有上传失败的图片。")
            return

        from views.project_detail_widget import flip_image_horizontally_replace, encode_image_to_data_url

        # 若当前打开的项目正显示预览图，先清空引用以免占用文件句柄
        detail = getattr(self.mw, "detail_widget", None)
        if detail and hasattr(detail, "lbl_preview"):
            detail.lbl_preview.clear()

        flipped_ok = []
        flipped_err = {}
        new_data_urls = {}

        for p in failed_paths:
            try:
                flip_image_horizontally_replace(p)
                flipped_ok.append(p)
                new_data_urls[p] = encode_image_to_data_url(p)
            except Exception as e:
                flipped_err[p] = str(e)

        # 同步更新批次任务中的 Base64 数据与失败提示说明
        ok_set = set(flipped_ok)
        for b in self.batches:
            for p in list((b.get("upload_failed") or {}).keys()):
                if p in ok_set:
                    b["upload_failed"][p] = "已左右翻转（待重新上传）"
            for t in b.get("tasks") or []:
                lp = t.get("local_image_path")
                if lp in new_data_urls and new_data_urls[lp]:
                    t["image_data_url"] = new_data_urls[lp]
                    t["imageDataUrl"] = new_data_urls[lp]
                elp = t.get("end_local_image_path")
                if elp in new_data_urls and new_data_urls[elp]:
                    t["end_image_data_url"] = new_data_urls[elp]
                    t["endImageDataUrl"] = new_data_urls[elp]

        # 同步刷新项目管理资源面板（若已打开）
        if detail and getattr(detail, "project_path", None):
            try:
                detail.refresh_media_list()
                detail.on_media_selection_changed(detail.list_media.currentItem(), None)
            except Exception:
                pass

        self.refresh_all()

        if flipped_ok:
            names_str = "、".join(Path(p).name for p in flipped_ok)
            self._log(f"↔️ 已左右翻转并替换 {len(flipped_ok)} 张失败图片：{names_str}")
        if flipped_err:
            err_str = "；".join(f"{Path(p).name}({r})" for p, r in flipped_err.items())
            self._log(f"❌ 有 {len(flipped_err)} 张图片翻转失败：{err_str}")

        if flipped_ok:
            err_note = f"\n\n⚠️ 另有 {len(flipped_err)} 张翻转失败：\n" + "\n".join(
                f"{Path(p).name}: {r}" for p, r in list(flipped_err.items())[:8]
            ) if flipped_err else ""
            reply = QMessageBox.question(
                self, "翻转完成",
                f"已成功将 {len(flipped_ok)} 张上传失败的图片左右翻转！\n"
                f"（新图片已替换并删除原图，保留原文件名）{err_note}\n\n"
                f"是否立即重新上传这些失败图片？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.start_upload(retry_only=True)
        else:
            QMessageBox.critical(
                self, "翻转失败",
                "所有失败图片翻转均未成功：\n\n" + "\n".join(f"{Path(p).name}: {r}" for p, r in list(flipped_err.items())[:10])
            )

    # ──────────────────────────────── RPC 响应
    def _on_rpc_response(self, payload):
        msg = payload.get("message") or {}
        action = msg.get("action", "")
        req = msg.get("request_id")
        if action == "upload_images_response":
            job = self.upload_pending.pop(req, None)
            data = msg.get("data") or {}
            ok_paths = list(data.get("uploaded") or []) + list(data.get("skipped") or [])
            failed = list(data.get("failed") or [])
            errors = data.get("errors") or {}
            if job:
                entry = job["entry"]
            else:
                # 超时后迟到的响应：仍然更新结果
                entry = next((e for e in self.plan.values() if e["cid"] == payload.get("client_id")), None)
                if not entry:
                    return
            self._mark_upload_result(entry, ok_paths, failed, errors)
            label = self._label(entry["email"])
            if failed:
                self._log(f"   ❌ {label}：成功 {len(ok_paths)} 张，失败 {len(failed)} 张：" + "、".join(Path(p).name for p in failed))
            else:
                self._log(f"   ✅ {label}：{len(ok_paths)} 张全部上传成功" + (f"（其中 {len(data.get('skipped') or [])} 张已存在）" if data.get("skipped") else ""))
        elif action == "run_tasks_response":
            data = msg.get("data") or {}
            b = self._batch(data.get("batch_id"))
            if not b:
                return
            if msg.get("success"):
                b["run_state"] = "生成中"
                self._log(f"🚀 {b['short']} 已被 {self._label(b['email'])} 接收（{data.get('count')} 个任务），开始生成")
            else:
                b["run_state"] = "发送失败"
                self._log(f"❌ {b['short']} 发送失败：{msg.get('error')}")
                QTimer.singleShot(500, lambda e=self.plan.get(b["cid"]): e and self._dispatch_next(e))
            self.refresh_all()
        elif action == "clear_tasks_response":
            label = self._label_for_client_id(payload.get("client_id", ""))
            data = msg.get("data", {}) or {}
            if msg.get("success"):
                self._log(f"✅ 已清空插件任务（{data.get('cleared', 0)} 个）: {label}")
            else:
                self._log(f"❌ 清空插件任务失败: {label} - {msg.get('error', '')}")
        elif action == "clear_media_response":
            label = self._label_for_client_id(payload.get("client_id", ""))
            data = msg.get("data", {}) or {}
            before, after = data.get("before", "?"), data.get("after", "?")
            if msg.get("success"):
                note = data.get("note")
                self._log(f"✅ 已清空 Flow 媒体: {label}" + (f"（{note}）" if note else f"（{before} → {after}）"))
            else:
                self._log(f"❌ 清空 Flow 媒体失败: {label} - {msg.get('error', '')}（{before} → {after}）")

    def _batch(self, bid):
        return next((b for b in self.batches if b["id"] == bid), None)

    # ──────────────────────────────── 步骤 3：发送任务并监控
    def start_run(self):
        if self.upload_group_active or self.upload_queue:
            QMessageBox.warning(self, "提示", "图片还在上传中，请等待上传结束。")
            return
        if not self.plan:
            QMessageBox.information(self, "提示", "请先完成步骤 1 的任务分配。")
            return
        ready = [b for b in self.batches if b["cid"] and b["upload_state"] == "成功" and b["run_state"] in ("未开始", "发送失败", "连接断开")]
        not_ready = [b for b in self.batches if b["cid"] and b["upload_state"] != "成功" and b["run_state"] == "未开始"]
        if not ready:
            QMessageBox.information(self, "提示", "没有可以发送的批次。\n\n只有图片全部上传成功的批次才会发送（请先完成步骤 2）。")
            return
        if not_ready:
            names = "、".join(b["short"] for b in not_ready[:6])
            if QMessageBox.question(self, "部分批次图片未上传成功",
                                    f"有 {len(not_ready)} 批图片未全部上传成功，将暂不发送：\n{names}\n\n是否先发送其余 {len(ready)} 批？",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                return
        for b in ready:
            if b["run_state"] != "未开始":
                b["run_state"] = "未开始"
        self.running = True
        self._log(f"🚀 步骤3 开始：{len(ready)} 批任务将发送到 {len({b['cid'] for b in ready})} 个浏览器")
        for entry in list(self.plan.values()):
            self._dispatch_next(entry)
        self.refresh_all()

    def _dispatch_next(self, entry):
        if not self.running:
            return
        mine = [b for b in self.batches if b["id"] in entry["batch_ids"]]
        if any(b["run_state"] in ("已发送", "生成中") for b in mine):
            return   # 该浏览器还在跑上一批
        nxt = next((b for b in mine if b["run_state"] == "未开始" and b["upload_state"] == "成功"), None)
        if not nxt:
            self._check_all_done()
            return
        c = self._resolve_client(entry)
        if not c:
            nxt["run_state"] = "连接断开"
            self._log(f"❌ {self._label(entry['email'])} 未连接，{nxt['short']} 无法发送")
            self.refresh_all()
            return
        nxt["run_state"] = "已发送"
        req = self.plugin_server.send_rpc_action(c["client_id"], "run_tasks",
                                                 {"batch_id": nxt["id"], "tasks": nxt["tasks"], "clear_existing": True})
        if not req:
            nxt["run_state"] = "发送失败"
        else:
            self._log(f"📨 已发送 {nxt['short']}（{len(nxt['tasks'])} 个任务）→ {self._label(entry['email'])}")
        self.refresh_all()

    def _on_hosted_event(self, payload):
        msg = payload.get("message") or {}
        b = self._batch(msg.get("batch_id"))
        if not b:
            return
        if payload.get("type") == "hosted_task_status":
            if msg.get("status") == "success":
                self._record_success(b, msg.get("download_path", ""))
            self.refresh_all()
            return

        # hosted_batch_finished —— 以插件最终报告为准
        for r in msg.get("results") or []:
            dp = r.get("download_path", "")
            if r.get("status") == "success":
                self._record_success(b, dp)
            elif dp not in b["done_paths"]:
                b["fail_msgs"][dp] = r.get("message") or "失败"
        b["ok"] = len(b["done_paths"])
        b["fail"] = len([k for k in b["fail_msgs"] if k not in b["done_paths"]])
        b["run_state"] = "完成"
        self._log(f"🏁 {b['short']} 完成：✅ 成功 {b['ok']}，❌ 失败 {b['fail']}"
                  + (("：" + "、".join(Path(k).name for k in b["fail_msgs"] if k not in b["done_paths"])) if b["fail"] else "")
                  + ("（插件被手动停止）" if msg.get("stopped") else ""))
        self._after_project_change(b["project_path"], reload_list=True)
        entry = self.plan.get(b["cid"])
        self.refresh_all()
        if entry:
            QTimer.singleShot(1500, lambda e=entry: self._dispatch_next(e))

    def _record_success(self, b, dl_path):
        if not dl_path or dl_path in b["done_paths"]:
            return
        b["done_paths"].add(dl_path)
        b["fail_msgs"].pop(dl_path, None)
        b["ok"] = len(b["done_paths"])
        name = Path(dl_path).name
        self._log(f"   🎬 视频已下载: {name}（保留在 Flow 目录，待后续批量检查归位）")

    def _after_project_change(self, project_path, reload_list=False):
        try:
            d = self.mw.detail_widget
            if d.project_path and str(d.project_path) == str(project_path):
                d.populate_segments_table()
            if reload_list:
                QTimer.singleShot(300, self.mw.reload_projects_list)
        except Exception as e:
            logger.warning(f"刷新项目界面失败: {e}")

    def _check_all_done(self):
        if not self.running:
            return
        active = [b for b in self.batches if b["run_state"] in ("已发送", "生成中")]
        waiting = [b for b in self.batches if b["cid"] and b["run_state"] == "未开始" and b["upload_state"] == "成功"]
        if active or waiting:
            return
        self.running = False
        ok = sum(b["ok"] for b in self.batches)
        fail = sum(b["fail"] for b in self.batches)
        self._log(f"🎉 全部批次执行结束：✅ 成功 {ok} 个视频，❌ 失败 {fail} 个。"
                  + ("失败的分句可再次点击「分配」重新生成（已成功的会自动排除）" if fail else ""))
        self.refresh_all()

    def stop_run(self):
        stopped_upload = bool(self.upload_queue or self.upload_group_active)
        self.upload_queue = []
        if stopped_upload:
            for job in self.upload_pending.values():
                self._mark_upload_result(job["entry"], [], job["paths"], {p: "已手动停止" for p in job["paths"]})
            self.upload_pending = {}
            self.upload_group_active = False
            self.upload_timer.stop()
            self._log("⏹ 已停止上传")
        if self.running:
            self.running = False
            for b in self.batches:
                if b["run_state"] in ("已发送", "生成中"):
                    c = self._resolve_client(self.plan.get(b["cid"], {"cid": b["cid"], "email": b["email"]}))
                    if c:
                        self.plugin_server.send_rpc_action(c["client_id"], "stop_tasks", {})
            self._log("⏹ 已停止派发，并通知正在生成的插件停止（已提交到 Flow 的不会取消）")
        self.refresh_all()

    def _on_client_disconnected(self, client_id):
        for b in self.batches:
            if b.get("cid") == client_id and b["run_state"] in ("已发送", "生成中"):
                b["run_state"] = "连接断开"
                self._log(f"⚠️ {self._label(b['email'])} 断开连接，{b['short']} 中断（重新连接后可再次点击步骤3继续）")
        self._schedule_refresh()
        QTimer.singleShot(200, self._check_all_done)
