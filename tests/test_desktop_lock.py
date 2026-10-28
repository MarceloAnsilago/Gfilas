import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import desktop_panel


@unittest.skipUnless(sys.platform == "win32", "Windows file locks")
class DesktopLockTests(unittest.TestCase):
    def test_existing_file_blocks_second_instance_and_can_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            for _ in range(3):
                handle = desktop_panel.acquire_single_instance_lock(base_dir)
                try:
                    with self.assertRaises(RuntimeError):
                        desktop_panel.acquire_single_instance_lock(base_dir)
                finally:
                    desktop_panel.release_single_instance_lock(handle)
            self.assertEqual((base_dir / "painel.lock").stat().st_size, 32)

    def test_startup_failure_is_shown_and_lock_is_released(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(desktop_panel, "get_runtime_dir", return_value=directory), \
                 patch.object(desktop_panel, "setup_logging"), \
                 patch.object(desktop_panel, "load_desktop_config", side_effect=desktop_panel.PrintAgentConfigError("Impressora indisponivel")), \
                 patch.object(desktop_panel, "show_startup_error") as show:
                self.assertEqual(desktop_panel.main(), 1)
                show.assert_called_once_with("Impressora indisponivel", Path(directory))
            handle = desktop_panel.acquire_single_instance_lock(Path(directory))
            desktop_panel.release_single_instance_lock(handle)
