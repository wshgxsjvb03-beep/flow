import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from services.video_relocation import relocate_downloaded_video


class VideoRelocationTests(unittest.TestCase):
    def paths(self, directory):
        root = Path(directory)
        project = root / 'projects' / '02_sample-flow'
        project.mkdir(parents=True)
        browser = root / 'browser-downloads'
        source = browser / 'Flow' / project.name / '03.mp4'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'completed-video-data')
        target = project / 'downloads' / 'videos' / '03.mp4'
        return project, browser, source, target

    def test_moves_only_completed_exact_project_file_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            project, browser, source, target = self.paths(directory)
            other = browser / 'Flow' / 'another-project' / '03.mp4'
            other.parent.mkdir()
            other.write_bytes(b'other-project-video')
            partial = source.with_suffix('.mp4.crdownload')
            partial.write_bytes(b'incomplete')
            result = relocate_downloaded_video(project, target, [browser])
            self.assertEqual(result['status'], 'moved')
            self.assertEqual(target.read_bytes(), b'completed-video-data')
            self.assertFalse(source.exists())
            self.assertEqual(other.read_bytes(), b'other-project-video')
            self.assertTrue(partial.exists())
            self.assertEqual(relocate_downloaded_video(project, target, [browser])['status'], 'already')

    def test_existing_target_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            project, browser, source, target = self.paths(directory)
            target.parent.mkdir(parents=True)
            target.write_bytes(b'previous-valid-video')
            self.assertEqual(relocate_downloaded_video(project, target, [browser])['status'], 'already')
            self.assertEqual(target.read_bytes(), b'previous-valid-video')
            self.assertTrue(source.exists())

    def test_ambiguous_sources_and_outside_destinations_are_not_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            project, browser, source, target = self.paths(directory)
            second = Path(directory) / 'second-browser'
            duplicate = second / 'Flow' / project.name / '03.mp4'
            duplicate.parent.mkdir(parents=True)
            duplicate.write_bytes(b'another-video')
            self.assertEqual(relocate_downloaded_video(project, target, [browser, second])['status'], 'error')
            self.assertEqual(relocate_downloaded_video(project, project.parent / '03.mp4', [browser])['status'], 'error')
            self.assertTrue(source.exists())
            self.assertFalse(target.exists())

    def test_unfinished_or_changed_source_is_retried_without_publishing_partial_target(self):
        with tempfile.TemporaryDirectory() as directory:
            project, browser, source, target = self.paths(directory)
            source.unlink()
            self.assertEqual(relocate_downloaded_video(project, target, [browser])['status'], 'missing')
            source.write_bytes(b'video')
            def changing_copy(incoming, outgoing, *args):
                outgoing.write(incoming.read())
                with source.open('ab') as file:
                    file.write(b'not-finished')
            with patch('services.video_relocation.shutil.copyfileobj', side_effect=changing_copy):
                self.assertEqual(relocate_downloaded_video(project, target, [browser])['status'], 'retry')
            self.assertFalse(target.exists())
            self.assertTrue(source.exists())
            self.assertEqual(list(target.parent.glob('.relocating-*')), [])


class HostedRelocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_success_notification_archives_in_background_and_duplicate_does_not_repeat(self):
        from models.project_model import ProjectModel
        from views.main_window import MainWindow
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'projects' / 'sample'
            project.mkdir(parents=True)
            model = ProjectModel(project)
            model.spanish_segments = [{'text': 'Hola'} for _ in range(3)]
            model.save()
            (root / '.app_config.json').write_text(json.dumps({
                'base_path': str(project.parent), 'enable_plugin_server': False}), encoding='utf-8')
            source = project.parent / 'Flow' / project.name / '03.mp4'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'hosted-completed-video')
            target = project / 'downloads' / 'videos' / '03.mp4'
            window = MainWindow(root)
            hosted = window.hosted_mode
            try:
                batch = {'tasks': [{'download_path': str(target)}], 'project_path': str(project),
                         'done_paths': set(), 'fail_msgs': {}, 'ok': 0}
                with patch.object(hosted, '_after_project_change') as refresh, \
                        patch.object(hosted, '_log') as log:
                    hosted._record_success(batch, str(target))
                    hosted._record_success(batch, str(target))
                    deadline = time.monotonic() + 5
                    while hosted._relocation_jobs and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(0.01)
                    self.assertFalse(hosted._relocation_jobs)
                    self.assertEqual(target.read_bytes(), b'hosted-completed-video')
                    self.assertFalse(source.exists())
                    self.assertEqual(batch['ok'], 1)
                    refresh.assert_called_once_with(str(project), reload_list=True)
                    self.assertEqual(sum('视频已下载' in call.args[0] for call in log.call_args_list), 1)
            finally:
                if hosted._relocation_pool:
                    hosted._relocation_pool.shutdown(wait=True)
                window.close()

    def test_queue_finish_waits_for_pending_archives(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from views.hosted_mode_widget import HostedModeWidget
        state = SimpleNamespace(running=True, batches=[], _relocation_jobs={'pending': {}}, _log=Mock(), refresh_all=Mock())
        HostedModeWidget._check_all_done(state)
        self.assertTrue(state.running)
        state._relocation_jobs.clear()
        HostedModeWidget._check_all_done(state)
        self.assertFalse(state.running)
