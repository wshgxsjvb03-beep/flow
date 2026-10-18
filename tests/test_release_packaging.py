"""Validate cloud packaging using temporary fake app files, without building apps."""
import ctypes
import json
import os
from pathlib import Path
import plistlib
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from scripts.package_release import (PUBLIC_FILES, collect_release, extension_files,
    package_extension, package_windows, prepare_desktop, validate_tag)


class ReleasePackagingTests(unittest.TestCase):
    def seed_public_files(self, root):
        for name in PUBLIC_FILES:
            (root / name).write_text('public example', encoding='utf-8')
        (root / '.env').write_text('PRIVATE_TEST_VALUE=not-for-release')

    def test_extension_archive_contains_only_manifest_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            extension = root / 'extension'
            extension.mkdir()
            (extension / 'manifest.json').write_text(json.dumps({'manifest_version': 3,
                'background': {'service_worker': 'background.js'}}))
            (extension / 'background.js').write_text('/* fake extension */')
            (extension / '.env').write_text('private')
            (extension / 'notes.txt').write_text('unrelated')
            archive = package_extension(root, root / 'output', 'v1.8.1')
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(set(bundle.namelist()), {'manifest.json', 'background.js'})

    def test_missing_or_escaping_extension_resources_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'private.js').write_text('private')
            extension = root / 'extension'
            extension.mkdir()
            for value in ('missing.js', '../private.js'):
                (extension / 'manifest.json').write_text(json.dumps({'background': {'service_worker': value}}))
                with self.assertRaises(ValueError):
                    extension_files(extension)

    def test_windows_bundle_keeps_directory_and_uses_only_example_configs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.seed_public_files(root)
            desktop = root / 'dist' / 'Flow'
            desktop.mkdir(parents=True)
            (desktop / 'Flow.exe').write_bytes(b'fake exe')
            archive = package_windows(root, root / 'output', 'v1.8.1')
            with zipfile.ZipFile(archive) as bundle:
                self.assertIn('Flow/Flow.exe', bundle.namelist())
                self.assertIn('Flow/.env.example', bundle.namelist())
                self.assertNotIn('Flow/.env', bundle.namelist())
                self.assertEqual(bundle.read('Flow/prompt_templates.json'), b'public example')

    def test_mac_preparation_removes_default_icon_before_signing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.seed_public_files(root)
            resources = root / 'dist' / 'Flow.app' / 'Contents' / 'Resources'
            resources.mkdir(parents=True)
            (resources / 'icon-windowed.icns').write_bytes(b'icon')
            info = resources.parent / 'Info.plist'
            with info.open('wb') as output:
                plistlib.dump({'CFBundleIconFile': 'icon-windowed.icns', 'CFBundleName': 'Flow'}, output)
            prepare_desktop(root, 'macos')
            self.assertFalse((resources / 'icon-windowed.icns').exists())
            with info.open('rb') as incoming:
                self.assertEqual(plistlib.load(incoming), {'CFBundleName': 'Flow'})
            self.assertTrue((resources / 'prompt_templates.json').exists())

    def test_both_mac_architectures_become_one_of_exactly_three_release_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            incoming = root / 'incoming'
            incoming.mkdir()
            for name in ('windows', 'extension', 'macos-arm64', 'macos-x86_64'):
                (incoming / f'Flow-{name}-v1.8.1.zip').write_bytes(b'fake archive')

            def fake_ditto(command, check):
                self.assertTrue(check)
                if '-x' in command:
                    executable = Path(command[-1]) / 'Flow.app' / 'Contents' / 'MacOS' / 'Flow'
                    executable.parent.mkdir(parents=True)
                    executable.write_bytes(b'fake executable')
                else:
                    Path(command[-1]).write_bytes(b'combined mac archive')

            with patch('scripts.package_release.subprocess.run', side_effect=fake_ditto):
                collect_release(root, incoming, root / 'release', 'v1.8.1')
            self.assertEqual({path.name for path in (root / 'release').iterdir()},
                {'Flow-windows-v1.8.1.zip', 'Flow-macos-v1.8.1.zip', 'Flow-extension-v1.8.1.zip'})
            self.assertTrue((root / 'release-stage/Flow-macos/Apple Silicon/Flow.app').is_dir())
            self.assertTrue((root / 'release-stage/Flow-macos/Intel/Flow.app').is_dir())

    def test_release_tag_rejects_path_and_shell_input(self):
        self.assertEqual(validate_tag('v1.8.1-beta.2'), 'v1.8.1-beta.2')
        for tag in ('main', '../v1', 'v1/../../bad', 'v1;echo bad', 'v1\nnext'):
            with self.assertRaises(ValueError):
                validate_tag(tag)

    def test_spec_builds_a_mac_app_bundle_only_on_macos(self):
        from PyInstaller.utils import hooks
        root = Path(__file__).resolve().parent.parent
        analysis = SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
        for platform in ('win32', 'darwin'):
            bundle = Mock()
            namespace = {'Analysis': Mock(return_value=analysis), 'PYZ': Mock(),
                'EXE': Mock(), 'COLLECT': Mock(), 'BUNDLE': bundle}
            with patch('sys.platform', platform), patch.object(hooks, 'copy_metadata', return_value=[]):
                exec(compile((root / 'flow.spec').read_text(encoding='utf-8'), 'flow.spec', 'exec'), namespace)
            self.assertEqual(bundle.call_count, int(platform == 'darwin'))
            if platform == 'darwin':
                self.assertEqual(bundle.call_args.kwargs['name'], 'Flow.app')

    def test_non_windows_pipeline_import_does_not_load_windows_apis(self):
        root = Path(__file__).resolve().parent.parent
        windows_api = Mock()
        with patch('sys.platform', 'darwin'), patch.object(ctypes, 'windll', windows_api, create=True):
            module = runpy.run_path(str(root / 'views/pipeline_tab_widget.py'))
            self.assertIsNone(module['_user32'])
            self.assertFalse(module['FileDialogAutomation'].fill_and_confirm('/tmp/image.png')[0])
        self.assertEqual(windows_api.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
