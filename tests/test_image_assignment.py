import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from services.image_assignment import natural_image_key, parse_sentence_range, plan_image_assignment


class AssignmentRulesTests(unittest.TestCase):
    def test_default_zero_is_equal_and_not_excluded(self):
        from collections import Counter
        for priority in (0, 3):
            plan = plan_image_assignment([{} for _ in range(12)], ['A', 'B', 'C'],
                end_frames=False, preserve=False, cycle=True,
                priorities={name: priority for name in ['A', 'B', 'C']})
            self.assertEqual(Counter(p['image_name'] for p in plan), {'A': 4, 'B': 4, 'C': 4})

    def test_priority_levels_increase_shares_and_interleave(self):
        from collections import Counter
        plan = plan_image_assignment([{} for _ in range(30)], ['A', 'B', 'C', 'D'],
            end_frames=False, preserve=False, cycle=True, priorities={'A': 0, 'B': 1, 'C': 2, 'D': 3})
        sequence = [p['image_name'] for p in plan]
        self.assertEqual(Counter(sequence), {'A': 3, 'B': 6, 'C': 9, 'D': 12})
        self.assertNotIn(['D'] * 4, [sequence[i:i + 4] for i in range(27)])
        for level in (-1, 100, 1.5):
            with self.assertRaises(ValueError):
                plan_image_assignment([{}], ['A'], priorities={'A': level})

    def test_ranges_accept_multiple_groups_and_reject_invalid_input(self):
        self.assertEqual(parse_sentence_range('1 - 3，5、7至8', 8), [0, 1, 2, 4, 6, 7])
        for value in ['0', '9', '4-2', '1-ab', '']:
            with self.assertRaises(ValueError):
                parse_sentence_range(value, 8)

    def test_weighted_cycle_only_uses_selected_pool(self):
        segments = [{} for _ in range(10)]
        plan = plan_image_assignment(segments, ['A', 'B'], range(1, 9), end_frames=False,
                                     preserve=False, cycle=True, priorities={'A': 2, 'B': 0, 'C': 9})
        self.assertEqual([p['image_name'] for p in plan], ['A', 'A', 'B', 'A'] * 2)
        self.assertEqual([p['row'] for p in plan], list(range(1, 9)))
        self.assertEqual(segments, [{} for _ in range(10)])

    def test_one_image_can_cycle_in_frame_mode(self):
        plan = plan_image_assignment([{}, {}, {}], ['A'], cycle=True, preserve=False)
        self.assertEqual([(p['image_name'], p['end_image_name']) for p in plan], [('A', 'A')] * 3)

    def test_pinned_image_outside_pool_links_only_selected_neighbors(self):
        plan = plan_image_assignment([{} for _ in range(6)], ['A', 'B'], [1, 2, 3],
                                     cycle=True, preserve=False, overrides={2: {'image_name': 'special'}})
        self.assertEqual(plan[0]['end_image_name'], 'special')
        self.assertEqual(plan[1]['image_name'], 'special')
        self.assertEqual(plan[1]['end_image_name'], plan[2]['image_name'])
        self.assertNotIn('special', [p['image_name'] for p in (plan[0], plan[2])])

    def test_conflicting_adjacent_pins_are_not_applied(self):
        plan = plan_image_assignment([{}, {}], ['A', 'B'], cycle=True, preserve=False,
            overrides={0: {'end_image_name': 'X'}, 1: {'image_name': 'Y'}})
        self.assertTrue(all(not p['changes'] and '冲突' in p['status'] for p in plan))

    def test_selected_images_form_a_chain_without_changing_input(self):
        segments = [{'text': 'sample'} for _ in range(3)]
        before = copy.deepcopy(segments)
        plan = plan_image_assignment(segments, ['3.png', '7.png', '9.png', '12.png'], preserve=False)
        self.assertEqual([(p['image_name'], p['end_image_name']) for p in plan],
                         [('3.png', '7.png'), ('7.png', '9.png'), ('9.png', '12.png')])
        self.assertEqual(segments, before)

    def test_shortage_leaves_remaining_sentences_untouched(self):
        segments = [{'image_name': 'old.png', 'end_image_name': 'old-end.png'} for _ in range(3)]
        plan = plan_image_assignment(segments, ['1.png', '2.png'], preserve=False)
        self.assertTrue(plan[0]['changes'])
        self.assertEqual(plan[1]['changes'], {})
        self.assertEqual(plan[2]['image_name'], 'old.png')
        self.assertIn('图片不足', plan[2]['status'])

    def test_non_adjacent_selection_does_not_link_across_unselected_sentences(self):
        plan = plan_image_assignment([{} for _ in range(5)], ['a', 'b', 'c', 'd'], [1, 3], preserve=False)
        self.assertEqual([(p['row'], p['image_name'], p['end_image_name']) for p in plan],
                         [(1, 'a', 'b'), (3, 'c', 'd')])

    def test_existing_next_first_frame_is_used_as_an_anchor(self):
        plan = plan_image_assignment([{'image_name': '1'}, {'image_name': '2'}], ['1', '2', '3'])
        self.assertEqual(plan[0]['changes'], {'end_image_name': '2'})
        self.assertEqual(plan[1]['changes'], {'end_image_name': '3'})

    def test_conflicting_manual_choices_are_preserved_and_reported(self):
        segments = [{'image_name': '1', 'end_image_name': 'manual'}, {'image_name': '2'}]
        plan = plan_image_assignment(segments, ['1', '2', '3'])
        self.assertEqual(plan[0]['end_image_name'], 'manual')
        self.assertEqual(plan[1]['image_name'], '2')
        self.assertIn('不衔接', plan[0]['status'])

    def test_single_frame_mode_and_numeric_filename_sort(self):
        names = sorted(['10.png', '2.png', '1.png'], key=natural_image_key)
        plan = plan_image_assignment([{}, {}, {}], names, end_frames=False, preserve=False)
        self.assertEqual([p['image_name'] for p in plan], ['1.png', '2.png', '10.png'])
        self.assertTrue(all('end_image_name' not in p['changes'] for p in plan))

    def test_no_selected_images_does_not_fill_from_existing_anchors(self):
        plan = plan_image_assignment([{'image_name': 'old'}, {'image_name': 'other'}], [])
        self.assertTrue(all(not entry['changes'] for entry in plan))


class AssignmentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_filters_orders_and_previews_without_mutating_project(self):
        from PyQt6.QtCore import Qt
        from views.image_assignment_dialog import ImageAssignmentDialog
        segments = [{} for _ in range(3)]
        dialog = ImageAssignmentDialog(segments, ['10.png', '2.png', '1.png'],
                                       selected_rows=[1], selected_images=['1.png', '10.png'], end_frames=True)
        try:
            self.assertEqual(dialog.checked_image_names(), ['1.png', '10.png'])
            self.assertEqual([p['row'] for p in dialog.plan], [1])
            self.assertEqual(dialog.plan[0]['end_image_name'], '10.png')
            dialog.images.setCurrentRow(2)
            dialog.move_image(-1)
            dialog.move_image(-1)
            self.assertEqual(dialog.checked_image_names(), ['10.png', '1.png'])
            self.assertEqual(dialog.plan[0]['image_name'], '10.png')
            dialog.check_images(False)
            self.assertFalse(dialog.apply_button.isEnabled())
            dialog.reject()
            self.assertEqual(segments, [{}, {}, {}])
        finally:
            dialog.close()

    def test_dialog_previews_pins_and_applies_multiple_disjoint_groups(self):
        from PIL import Image
        from PyQt6.QtCore import Qt
        from views.image_assignment_dialog import ImageAssignmentDialog
        segments = [{'text': f'Sentence {i + 1}'} for i in range(8)]
        applied = []
        def apply(plan, mode):
            applied.append(copy.deepcopy(plan))
            for entry in plan:
                segments[entry['row']].update(entry['changes'])
            return True
        with tempfile.TemporaryDirectory() as folder:
            for name in ['A.png', 'B.png', 'special.png']:
                Image.new('RGB', (40, 60), 'red').save(Path(folder, name))
            dialog = ImageAssignmentDialog(segments, ['A.png', 'B.png', 'special.png'],
                selected_images=['A.png', 'B.png'], image_dir=folder, apply_callback=apply)
            try:
                self.assertEqual(dialog.priority_level.value(), 0)
                self.assertTrue(all(value == 0 for value in dialog.priorities.values()))
                self.assertFalse(dialog.images.item(0).icon().isNull())
                self.assertFalse(dialog.large_preview.pixmap().isNull())
                dialog.range_edit.setText('1-4')
                dialog.scope.setCurrentIndex(dialog.scope.findData('custom'))
                dialog.images.setCurrentRow(0)
                dialog.priority_level.setValue(2)
                self.assertEqual([p['image_name'] for p in dialog.plan], ['A.png', 'A.png', 'B.png', 'A.png'])
                dialog.preview.selectRow(1)
                dialog.pin_first.setCurrentIndex(dialog.pin_first.findData('special.png'))
                dialog.pin_selected_rows()
                self.assertEqual(dialog.plan[1]['image_name'], 'special.png')
                dialog.show()
                dialog.apply_current_batch()
                self.assertTrue(dialog.isVisible(), 'Apply must leave the window open')
                self.assertFalse(dialog.apply_button.isEnabled(), 'Applied pins must not immediately revert')
                self.assertEqual(segments[1]['image_name'], 'special.png')
                first_group = copy.deepcopy(segments[:4])
                dialog.range_edit.setText('5-8')
                dialog.check_images(False)
                dialog.images.item(1).setCheckState(Qt.CheckState.Checked)
                dialog.apply_current_batch()
                self.assertEqual(segments[:4], first_group)
                self.assertTrue(all(seg['image_name'] == 'B.png' for seg in segments[4:]))
                self.assertEqual(len(applied), 2)
                dialog.reject()
                self.assertEqual(segments[:4], first_group, 'Closing must retain saved batches')
            finally:
                dialog.close()

    def test_apply_and_undo_save_once_and_preserve_later_manual_changes(self):
        from PIL import Image
        from models.project_model import ProjectModel
        from views.main_window import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'projects' / 'example'
            downloads = project / 'downloads'
            downloads.mkdir(parents=True)
            for name in ['1.png', '2.png', '3.png', '4.png']:
                Image.new('RGB', (8, 8)).save(downloads / name)
            (root / '.app_config.json').write_text(json.dumps({
                'base_path': str(project.parent), 'enable_plugin_server': False
            }), encoding='utf-8')
            model = ProjectModel(project)
            model.spanish_segments = [{'text': 'Hola amigos'} for _ in range(5)]
            model.save()
            window = MainWindow(root)
            try:
                detail = window.detail_widget
                detail.set_project(project)
                segments = detail.project_model.spanish_segments
                before = copy.deepcopy(segments)
                plan = plan_image_assignment(segments, ['2.png', '3.png', '4.png'], [1, 2], preserve=False)
                with patch.object(ProjectModel, 'save', autospec=True, side_effect=ProjectModel.save) as save, \
                        patch('base64.b64encode', wraps=base64.b64encode) as encode:
                    detail.table_segments.selectRow(1)
                    save.assert_not_called()
                    self.assertTrue(detail.apply_image_assignment(plan, True))
                    self.assertEqual(save.call_count, 1)
                    self.assertEqual(segments[1]['end_image_name'], segments[2]['image_name'])
                    self.assertTrue(detail.chk_enable_end_frame.isChecked())
                    self.assertEqual(segments[0], before[0])
                    self.assertEqual(segments[3:], before[3:])
                    persisted = json.loads(detail.project_model.metadata_path.read_text(encoding='utf-8'))
                    self.assertTrue(persisted['enable_end_frame'])
                    self.assertEqual(persisted['spanish_segments'][1]['end_image_name'], '3.png')
                    segments[1]['image_name'] = '1.png'  # later manual edit
                    self.assertTrue(detail.undo_image_assignment())
                    self.assertEqual(save.call_count, 2)
                    self.assertEqual(segments[1]['image_name'], '1.png')
                    self.assertEqual(segments[1].get('end_image_name'), before[1].get('end_image_name'))
                    self.assertEqual(segments[2], before[2])
                    self.assertFalse(detail.enable_end_frame)
                    self.assertFalse(detail.btn_undo_image_assignment.isEnabled())
                    encode.assert_not_called()
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
