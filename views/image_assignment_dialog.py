from pathlib import Path
from collections import Counter
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from services.image_assignment import natural_image_key, parse_sentence_range, plan_image_assignment


class ImageAssignmentDialog(QDialog):
    def __init__(self, segments, image_names, selected_rows=(), selected_images=(),
                 end_frames=False, parent=None, *, image_dir=None, apply_callback=None):
        super().__init__(parent)
        self.setWindowTitle('分批分配图片')
        self.resize(1240, 820)
        self.setMinimumSize(960, 680)
        self.segments = segments
        self.initial_end_frames = end_frames
        self.selected_rows = sorted(set(selected_rows))
        self.plan, self.overrides, self.priorities, self.icons = [], {}, {}, {}
        self.apply_callback = apply_callback
        self.image_dir = Path(image_dir) if image_dir else None
        self.names = sorted(image_names, key=natural_image_key)
        self.applied_count = 0
        layout = QVBoxLayout(self)
        title = QLabel('选句子 → 勾图片、调优先级 → 预览并应用')
        title.setStyleSheet('font-size: 17px; font-weight: bold; color: #5D4037; padding: 6px;')
        layout.addWidget(title)
        options = QHBoxLayout()
        options.addWidget(QLabel('分配范围：'))
        self.scope = QComboBox()
        self.scope.addItem(f'全部分句（{len(segments)} 句）', 'all')
        self.scope.addItem(f'主表选中的分句（{len(self.selected_rows)} 句）', 'selected')
        self.scope.model().item(1).setEnabled(bool(self.selected_rows))
        self.scope.addItem('自定义句号', 'custom')
        if self.selected_rows:
            self.scope.setCurrentIndex(1)
        options.addWidget(self.scope)
        self.range_edit = QLineEdit(f'1-{len(segments)}')
        self.range_edit.setPlaceholderText('如 1-8,12,15-20')
        options.addWidget(self.range_edit, 1)
        select_rows = QPushButton('用预览选中行作范围')
        select_rows.clicked.connect(self.use_selected_rows)
        options.addWidget(select_rows)
        layout.addLayout(options)
        modes = QHBoxLayout()
        self.cycle = QCheckBox('循环所选图片')
        self.cycle.setChecked(True)
        modes.addWidget(self.cycle)
        self.end_frames = QCheckBox('首尾帧连续衔接（项目开关）')
        self.end_frames.setChecked(end_frames)
        modes.addWidget(self.end_frames)
        self.preserve = QCheckBox('只填空白，保留已有选择')
        self.preserve.setChecked(False)
        modes.addWidget(self.preserve)
        modes.addStretch()
        layout.addLayout(modes)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        left_layout.addWidget(QLabel('勾选本批图片；拖动排序。未勾选的图片不参与循环'))
        self.images = QListWidget()
        self.images.setIconSize(QSize(90, 72))
        self.images.setWordWrap(True)
        self.images.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.images.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.images.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        selected = set(selected_images)
        for name in self.names:
            self.priorities[name] = 0
            item = QListWidgetItem(self.icon_for(name), name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            item.setSizeHint(QSize(300, 86))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if not selected or name in selected else Qt.CheckState.Unchecked)
            self.images.addItem(item)
        left_layout.addWidget(self.images, 1)
        image_buttons = QHBoxLayout()
        for label, action in [('全选', lambda: self.check_images(True)), ('清空勾选', lambda: self.check_images(False)),
                              ('↑', lambda: self.move_image(-1)), ('↓', lambda: self.move_image(1))]:
            button = QPushButton(label)
            button.clicked.connect(action)
            image_buttons.addWidget(button)
        left_layout.addLayout(image_buttons)
        self.large_preview = QLabel('点击图片查看预览')
        self.large_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.large_preview.setFixedHeight(120)
        left_layout.addWidget(self.large_preview)
        frequency = QHBoxLayout()
        frequency.addWidget(QLabel('当前图片优先级'))
        self.priority_level = QSpinBox()
        self.priority_level.setRange(0, 99)
        frequency.addWidget(self.priority_level)
        frequency.addStretch()
        left_layout.addLayout(frequency)
        hint = QLabel('默认都是 0：平均分配；数值越大，分配越多。\n'
                      '按优先级穿插分配，不用计算使用次数。\n'
                      '某图只用于特定句：不要勾选该图，在右侧指定它。\n'
                      '点击右侧首帧 / 尾帧，可在下方查看大图。')
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        right_layout.addWidget(QLabel('预览中支持 Ctrl / Shift 多选；选中句子后可单独指定图片'))
        self.preview = QTableWidget(0, 5)
        self.preview.setHorizontalHeaderLabels(['句号', '文案', '首帧', '尾帧', '结果'])
        self.preview.setIconSize(QSize(72, 58))
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.preview.verticalHeader().hide()
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        right_layout.addWidget(self.preview, 1)
        pin_options = QHBoxLayout()
        self.pin_first = self.image_combo('首帧跟随自动分配')
        self.pin_last = self.image_combo('尾帧跟随自动分配')
        pin_options.addWidget(QLabel('指定首帧'))
        pin_options.addWidget(self.pin_first, 1)
        pin_options.addWidget(QLabel('指定尾帧'))
        pin_options.addWidget(self.pin_last, 1)
        right_layout.addLayout(pin_options)
        pin_actions = QHBoxLayout()
        pin = QPushButton('固定到选中句')
        pin.clicked.connect(self.pin_selected_rows)
        clear_pin = QPushButton('取消选中句的固定')
        clear_pin.clicked.connect(self.clear_selected_pins)
        pin_actions.addWidget(pin)
        pin_actions.addWidget(clear_pin)
        right_layout.addLayout(pin_actions)
        splitter.addWidget(right)
        splitter.setSizes([340, 850])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        note = QLabel('只修改本批范围，其他句子保持原样。固定某句首帧时，也会衔接本批上一句的尾帧。\n'
                      '应用后窗口保持打开：换句号、换图片，再应用下一批。关闭不会撤销已应用的批次。')
        note.setWordWrap(True)
        note.setStyleSheet('color: #795548; padding: 4px 0;')
        layout.addWidget(note)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.setText('应用本批，继续分配')
        self.apply_button.clicked.connect(self.apply_current_batch)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.scope.currentIndexChanged.connect(self.refresh_preview)
        self.range_edit.textChanged.connect(self.refresh_preview)
        self.cycle.toggled.connect(self.refresh_preview)
        self.end_frames.toggled.connect(self.refresh_preview)
        self.preserve.toggled.connect(self.refresh_preview)
        self.images.itemChanged.connect(self.refresh_preview)
        self.images.model().rowsMoved.connect(self.refresh_preview)
        self.images.currentItemChanged.connect(self.show_current_image)
        self.preview.cellClicked.connect(self.preview_image)
        self.priority_level.valueChanged.connect(self.change_priority)
        if self.images.count():
            self.images.setCurrentRow(0)
        self.refresh_preview()

    def icon_for(self, name):
        if name not in self.icons:
            icon = QIcon()
            if self.image_dir:
                reader = QImageReader(str(self.image_dir / name))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(220, 140, Qt.AspectRatioMode.KeepAspectRatio))
                image = reader.read()
                if not image.isNull():
                    icon = QIcon(QPixmap.fromImage(image))
            self.icons[name] = icon
        return self.icons[name]

    def image_combo(self, automatic_label):
        combo = QComboBox()
        combo.setMinimumContentsLength(12)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setIconSize(QSize(48, 40))
        combo.addItem(automatic_label, None)
        for name in self.names:
            combo.addItem(self.icon_for(name), name, name)
        return combo

    def checked_image_names(self):
        return [self.images.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.images.count())
                if self.images.item(i).checkState() == Qt.CheckState.Checked]

    def check_images(self, checked):
        self.images.blockSignals(True)
        for i in range(self.images.count()):
            self.images.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.images.blockSignals(False)
        self.refresh_preview()

    def move_image(self, offset):
        row = self.images.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < self.images.count():
            self.images.insertItem(target, self.images.takeItem(row))
            self.images.setCurrentRow(target)
            self.refresh_preview()

    def show_current_image(self, item, previous=None):
        self.priority_level.blockSignals(True)
        name = item.data(Qt.ItemDataRole.UserRole) if item else ''
        self.priority_level.setValue(self.priorities.get(name, 0))
        self.priority_level.setEnabled(bool(item))
        self.priority_level.blockSignals(False)
        pixmap = self.icon_for(name).pixmap(220, 116) if name else QPixmap()
        if not pixmap.isNull():
            self.large_preview.setPixmap(pixmap)
        else:
            self.large_preview.setText('图片无法预览' if item else '点击图片查看预览')
        self.large_preview.setToolTip(name)

    def change_priority(self, value):
        item = self.images.currentItem()
        if item:
            self.priorities[item.data(Qt.ItemDataRole.UserRole)] = value
            self.refresh_preview()

    def selected_preview_rows(self):
        return [self.plan[i.row()]['row'] for i in self.preview.selectionModel().selectedRows()
                if i.row() < len(self.plan)]

    def preview_image(self, row, column):
        if row < len(self.plan) and column in (2, 3):
            field = 'image_name' if column == 2 else 'end_image_name'
            name = self.plan[row][field]
            for i in range(self.images.count()):
                if self.images.item(i).data(Qt.ItemDataRole.UserRole) == name:
                    self.images.setCurrentRow(i)
                    break

    def use_selected_rows(self):
        rows = self.selected_preview_rows()
        if not rows:
            self.feedback.setText('请先在右侧预览中选择句子（支持 Ctrl / Shift 多选）。')
            return
        self.range_edit.setText(','.join(str(row + 1) for row in sorted(rows)))
        self.scope.setCurrentIndex(self.scope.findData('custom'))

    def pin_selected_rows(self):
        rows = self.selected_preview_rows()
        first, last = self.pin_first.currentData(), self.pin_last.currentData()
        if not rows or not (first or (last and self.end_frames.isChecked())):
            self.feedback.setText('先选中句子，再选择要固定的首帧或尾帧。')
            return
        for row in rows:
            fields = self.overrides.setdefault(row, {})
            if first:
                fields['image_name'] = first
            if last and self.end_frames.isChecked():
                fields['end_image_name'] = last
        self.refresh_preview()

    def clear_selected_pins(self):
        for row in self.selected_preview_rows():
            self.overrides.pop(row, None)
        self.refresh_preview()

    def apply_current_batch(self):
        if not self.apply_button.isEnabled():
            return
        changed = sum(bool(entry['changes']) for entry in self.plan)
        if self.apply_callback is None:
            self.feedback.setText('当前窗口没有连接项目保存操作。')
            return
        if not self.apply_callback(self.plan, self.end_frames.isChecked()):
            self.feedback.setText('本批未保存，请检查提示后重试。')
            return
        self.applied_count += 1
        self.initial_end_frames = self.end_frames.isChecked()
        self.refresh_preview()
        self.feedback.setText(f'第 {self.applied_count} 批已保存，更新 {changed} 句。可以更换句号和图片，继续下一批。')

    def refresh_preview(self, *args):
        selected = set(self.selected_preview_rows()) if self.plan else set()
        images = self.checked_image_names()
        self.range_edit.setEnabled(self.scope.currentData() == 'custom')
        self.pin_last.setEnabled(self.end_frames.isChecked())
        try:
            rows = (self.selected_rows if self.scope.currentData() == 'selected' else
                    parse_sentence_range(self.range_edit.text(), len(self.segments)) if self.scope.currentData() == 'custom' else None)
            self.plan = plan_image_assignment(self.segments, images, rows,
                end_frames=self.end_frames.isChecked(), preserve=self.preserve.isChecked(),
                cycle=self.cycle.isChecked(), priorities=self.priorities, overrides=self.overrides)
        except ValueError as error:
            self.plan = []
            self.preview.setRowCount(0)
            self.summary.setText(str(error))
            self.apply_button.setEnabled(False)
            return
        self.preview.setRowCount(len(self.plan))
        for i, entry in enumerate(self.plan):
            text = self.segments[entry['row']].get('text', '')
            values = [str(entry['row'] + 1), text, entry['image_name'] or '—',
                      entry['end_image_name'] or '—', entry['status']]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col in (2, 3) and value != '—':
                    item.setIcon(self.icon_for(value))
                self.preview.setItem(i, col, item)
            self.preview.setRowHeight(i, 78)
        self.preview.clearSelection()
        for i, entry in enumerate(self.plan):
            if entry['row'] in selected:
                for col in range(self.preview.columnCount()):
                    self.preview.item(i, col).setSelected(True)
        counts = Counter(entry['image_name'] for entry in self.plan)
        self.images.blockSignals(True)
        for i in range(self.images.count()):
            item = self.images.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setText(f'{name}\n优先级 {self.priorities[name]} · 本批首帧 {counts[name]} 句')
        self.images.blockSignals(False)
        changed = sum(bool(entry['changes']) for entry in self.plan)
        missing = sum('图片不足' in entry['status'] for entry in self.plan)
        conflicts = sum('指定首尾帧冲突' in entry['status'] for entry in self.plan)
        mode_changed = self.end_frames.isChecked() != self.initial_end_frames
        self.summary.setText(f'本批 {len(self.plan)} 句 · 已选 {len(images)} 张图片 · 将更新 {changed} 句 · 图片不足 {missing} 句 · 固定冲突 {conflicts} 句')
        self.apply_button.setEnabled(bool(self.plan and (changed or mode_changed) and not conflicts))
