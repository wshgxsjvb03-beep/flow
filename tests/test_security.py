"""Exercise hostile inputs at trust boundaries without contacting real services."""
import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from services.security import (https_host_allowed, get_with_checked_redirects,
                               report_video_path, publish_video_chunks, project_image_path)


class NetworkBoundaryTests(unittest.TestCase):
    def test_https_exact_hosts_reject_credentials_ports_controls_and_spoofs(self):
        self.assertTrue(https_host_allowed('https://api.gladia.io/v2/a', ('api.gladia.io',)))
        for url in ('http://api.gladia.io/a', 'https://api.gladia.io.evil/a',
                    'https://evil.api.gladia.io/a', 'https://api.gladia.io:8080/a',
                    'https://user@api.gladia.io/a', 'https://@api.gladia.io/a',
                    'https://api.gladia.io/\r\na', 'https://127.0.0.1/a'):
            self.assertFalse(https_host_allowed(url, ('api.gladia.io',)), url)

    def test_redirect_destination_is_rejected_before_any_second_request(self):
        response = Mock(status_code=302, headers={'Location': 'http://127.0.0.1/admin'})
        session = Mock()
        session.get.return_value = response
        with self.assertRaises(ValueError):
            get_with_checked_redirects(session, 'https://cdn.example/video',
                lambda url: https_host_allowed(url, ('cdn.example',)), stream=True)
        session.get.assert_called_once_with('https://cdn.example/video', allow_redirects=False, stream=True)
        response.close.assert_called_once()

    def test_gladia_never_sends_key_to_an_untrusted_result_url(self):
        from services.speech_extractor import SpeechExtractor
        upload = Mock(status_code=200)
        upload.json.return_value = {'audio_url': 'https://api.gladia.io/audio'}
        transcription = Mock(status_code=201)
        transcription.json.return_value = {'result_url': 'https://attacker.example/result'}
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder, 'clip.mp4')
            video.write_bytes(b'video')
            with patch.object(SpeechExtractor, 'extract_audio_from_video', return_value=None), \
                    patch('services.speech_extractor.requests.post', side_effect=[upload, transcription]) as post, \
                    patch('services.speech_extractor.requests.get') as get:
                result = SpeechExtractor.extract_with_gladia(video, 'test-key')
            self.assertFalse(result['success'])
            get.assert_not_called()
            self.assertTrue(all(call.kwargs['allow_redirects'] is False for call in post.call_args_list))


class FileBoundaryTests(unittest.TestCase):
    def test_manual_video_matching_does_not_select_backups_or_similar_projects(self):
        from services.video_checker import VideoChecker
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('01_sample-flow', '01_sample', '01_sample-flow-backup', '01_sample-other-flow'):
                (root / name).mkdir()
            matches = VideoChecker.find_project_folders(root, '01_sample-flow', 1, 'sample')
            self.assertEqual({item.name for item in matches}, {'01_sample-flow', '01_sample'})

    def test_image_metadata_cannot_read_files_outside_downloads(self):
        from views.project_detail_widget import ProjectDetailWidget, encode_image_to_data_url
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder, 'project')
            downloads = project / 'downloads'
            downloads.mkdir(parents=True)
            (downloads / 'good.png').write_bytes(b'good-image')
            secret = Path(folder, 'private.pem')
            secret.write_bytes(b'not-a-real-key')
            detail = SimpleNamespace(project_path=project, enable_end_frame=True)
            for name in ('../../private.pem', str(secret), 'C:relative.png'):
                self.assertIsNone(project_image_path(project, name))
                result = ProjectDetailWidget.resolve_segment_end_image_and_data(detail, 0, {'end_image_name': name})
                self.assertEqual(result, ('', '', ''))
            self.assertEqual(encode_image_to_data_url(secret), '')
            result = ProjectDetailWidget.resolve_segment_image_and_data(detail, 0, {'image_name': '../../private.pem'})
            self.assertEqual(result[0], 'good.png')
            self.assertEqual(base64.b64decode(result[2].split(',', 1)[1]), b'good-image')

    def test_reports_cannot_write_metadata_siblings_or_executables(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder, 'project')
            target = project / 'downloads' / 'videos' / '01.mp4'
            self.assertEqual(report_video_path(project, target), target.resolve())
            for value in (project / 'metadata.json', project.parent / 'other' / '01.mp4',
                          project / 'downloads' / 'videos' / 'payload.exe'):
                with self.assertRaises(ValueError):
                    report_video_path(project, value)
            publish_video_chunks(project, target, [b'original' * 200])
            with self.assertRaises(FileExistsError):
                publish_video_chunks(project, target, [b'overwritten' * 200])
            self.assertEqual(target.read_bytes(), b'original' * 200)
            self.assertFalse(list(target.parent.glob('.report-*')))

    def test_oversized_video_never_publishes_a_partial_target(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder, 'downloads', 'videos', '01.mp4')
            with self.assertRaises(ValueError):
                publish_video_chunks(folder, target, [b'x' * 2048], max_bytes=1024)
            self.assertFalse(target.exists())
            self.assertFalse(list(target.parent.glob('.report-*')))

    def test_batch_ids_cannot_overwrite_or_delete_outside_the_batch_directory(self):
        from models.batch_model import BatchProjectModel
        with tempfile.TemporaryDirectory() as folder:
            model = BatchProjectModel(folder)
            victim = Path(folder, 'victim.json')
            victim.write_text('preserve')
            for value in ('../victim', '..\\victim', str(victim.with_suffix('')), 'C:relative', 'bad\0id'):
                with self.assertRaises(ValueError):
                    model.delete_project(value)
                with self.assertRaises(ValueError):
                    model.save_project({'id': value})
            self.assertEqual(victim.read_text(), 'preserve')

    def test_metadata_project_id_cannot_escape_subtitle_directory(self):
        from models.project_model import ProjectModel
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder, 'project')
            project.mkdir()
            (project / 'metadata.json').write_text(json.dumps({'project_id': '../../escape',
                'spanish_segments': [{'text': 'test'}]}))
            model = ProjectModel(project)
            self.assertEqual(model.project_id, 'project')
            self.assertFalse(Path(folder, 'escape.txt').exists())


class PluginBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_malformed_messages_cannot_raise_out_of_qt_callback(self):
        from services.plugin_server import PluginServer
        server = PluginServer()
        socket = Mock()
        server.clients[socket] = {'client_id': 'worker'}
        for message in ([], None, 123, {'type': []}, {'type': 'status_update', 'remaining_points': 'NaN'},
                        {'type': 'status_update', 'remaining_points': None},
                        {'type': 'custom_response', 'data': {'remaining_points': None}},
                        {'type': 'online', 'client_id': []}, {'type': 'execution_report', 'data': [1]}):
            server.on_message_received(socket, json.dumps(message))
        socket.sendTextMessage.assert_not_called()

    def test_report_ignores_other_project_video_and_external_write_path(self):
        from views.project_detail_widget import ProjectDetailWidget
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = root / 'project'
            project.mkdir()
            other = root / 'Downloads' / 'Flow' / 'other-project' / '01.mp4'
            other.parent.mkdir(parents=True)
            other.write_bytes(b'other-project-video' * 100)
            model = SimpleNamespace(spanish_segments=[{'text': 'hello'}], save=Mock())
            detail = SimpleNamespace(project_path=project, project_model=model, copied_rows=set(),
                dispatched_indices={0}, populate_segments_table=Mock(), is_auto_polling_active=False)
            with patch('pathlib.Path.home', return_value=root), patch('views.project_detail_widget.QTimer.singleShot'):
                ProjectDetailWidget.on_plugin_report_received(detail, {'data': [{'index': 0, 'status': 'success'}]})
                self.assertTrue(other.exists())
                self.assertFalse(model.spanish_segments[0].get('completed'))
                ProjectDetailWidget.on_plugin_report_received(detail, {'data': [{'index': 0,
                    'download_path': str(project / 'metadata.json'),
                    'base64Data': base64.b64encode(b'new-video' * 200).decode()}]})
            self.assertFalse((project / 'metadata.json').exists())
            self.assertTrue((project / 'downloads' / 'videos' / '01.mp4').exists())
            self.assertTrue(model.spanish_segments[0]['completed'])
            self.assertTrue(other.exists())

    def test_updater_entry_points_have_been_removed(self):
        from views.main_window import MainWindow
        self.assertFalse(hasattr(MainWindow, '_silent_update_check'))
        self.assertFalse(hasattr(MainWindow, 'open_update_dialog'))
        root = Path(__file__).resolve().parent.parent
        self.assertFalse((root / 'services' / 'updater.py').exists())
        self.assertFalse((root / 'views' / 'update_dialog.py').exists())


if __name__ == '__main__':
    unittest.main()
