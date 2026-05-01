"""
Tests for the installer and CLI capabilities logic.

This file covers:
1. test_default_installation: Standard service install (root, LAN, systemd).
2. test_foreground_only_installation: Internet mode without systemd.
3. test_cli_warning_when_stages_missing: CLI warns when not initialized.
4. test_sudo_skipping: Sudo-required stages are skipped for non-root users.
"""
import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import shutil
import tempfile

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

import guga.installer as installer
import guga.cli as cli

class TestGugaInstaller(unittest.TestCase):
    def setUp(self):
        # Each test gets its own isolated temp directory and fresh DB.
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.test_dir, ".guga")
        os.makedirs(self.config_dir, exist_ok=True)
        self.db_path = os.path.join(self.config_dir, "guga_test.db")

        # Import here so we always get the latest reference
        from guga.db_utils import Database
        self.fresh_db = Database(self.db_path)

        # Patch the db singleton used by installer and cli to our fresh instance
        self.patcher_inst_db = patch.object(installer, 'db', self.fresh_db)
        self.patcher_cli_db = patch.object(cli, 'db', self.fresh_db)

        # Patch CONFIG_DIR so .env writes go to temp dir
        self.patcher_inst_cfg = patch.object(installer, 'CONFIG_DIR', self.config_dir)
        self.patcher_inst_cap = patch.object(installer, 'CAPABILITIES_FILE',
                                             os.path.join(self.config_dir, "capabilities.json"))

        self.patcher_inst_db.start()
        self.patcher_cli_db.start()
        self.patcher_inst_cfg.start()
        self.patcher_inst_cap.start()

    def tearDown(self):
        self.patcher_inst_db.stop()
        self.patcher_cli_db.stop()
        self.patcher_inst_cfg.stop()
        self.patcher_inst_cap.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch('guga.installer.is_root')
    @patch('guga.installer.ask')
    @patch('guga.installer.install_linux_packages')
    @patch('guga.installer.setup_man_page')
    @patch('guga.installer.install_systemd_service')
    @patch('guga.installer.shutil.which')
    @patch('guga.installer.platform.system')
    def test_default_installation(self, mock_platform, mock_which, mock_systemd,
                                  mock_man, mock_packages, mock_ask, mock_root):
        """1. Test a default installation (Standard Service, Root)"""
        mock_root.return_value = True
        mock_platform.return_value = "Linux"
        mock_which.return_value = "/usr/bin/something"

        # Responses: mode=1 (LAN), os_notif=n, adv_choice=1 (Standard Service)
        mock_ask.side_effect = ["1", "n", "1"]

        installer.run_system_installer()

        state = self.fresh_db.get_capabilities()
        self.assertIn("system_packages", state["installed_stages"])
        self.assertIn("systemd_service", state["installed_stages"])
        self.assertTrue(state["capabilities"].get("background_service"))

        mock_packages.assert_called_once()
        mock_man.assert_called_once()
        mock_systemd.assert_called_once()

    @patch('guga.installer.is_root')
    @patch('guga.installer.ask')
    @patch('guga.installer.install_linux_packages')
    @patch('guga.installer.download_cloudflared')
    @patch('guga.installer.setup_man_page')
    @patch('guga.installer.install_systemd_service')
    @patch('guga.installer.shutil.which')
    @patch('guga.installer.platform.system')
    def test_foreground_only_installation(self, mock_platform, mock_which, mock_systemd,
                                          mock_man, mock_cloudflared, mock_packages,
                                          mock_ask, mock_root):
        """2. Test a foreground only installation (Internet Mode)"""
        mock_root.return_value = True
        mock_platform.return_value = "Linux"
        mock_which.return_value = "/usr/bin/something"

        # Responses: mode=2 (Public/Internet), os_notif=n, adv_choice=2 (Foreground Only)
        mock_ask.side_effect = ["2", "n", "2"]

        installer.run_system_installer()

        state = self.fresh_db.get_capabilities()
        self.assertIn("cloudflared", state["installed_stages"])
        self.assertIn("system_packages", state["installed_stages"])
        self.assertNotIn("systemd_service", state["installed_stages"])
        self.assertFalse(state["capabilities"].get("background_service"))

        mock_cloudflared.assert_called_once()
        mock_systemd.assert_not_called()

    @patch('sys.stdout', new_callable=MagicMock)
    def test_cli_warning_when_stages_missing(self, mock_stdout):
        """3. CLI warns when no stages are installed."""
        # Empty capabilities — nothing installed
        self.fresh_db.save_capabilities({"installed_stages": [], "capabilities": {}})

        mock_args = MagicMock()
        mock_args.install_service = False
        mock_args.uninstall = False
        mock_args.version = False
        mock_args.status = False

        cli.check_capabilities(mock_args)

        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        self.assertIn("GuGa hasn't been fully initialized", output)
        self.assertIn("guga --install-service", output)

    @patch('guga.installer.is_root')
    @patch('guga.installer.ask')
    @patch('guga.installer.platform.system')
    @patch('guga.installer.install_linux_packages')
    def test_sudo_skipping(self, mock_packages, mock_platform, mock_ask, mock_root):
        """4. Sudo stages are skipped when not root."""
        mock_root.return_value = False
        mock_platform.return_value = "Linux"
        mock_ask.side_effect = ["1", "n", "1"]

        installer.run_system_installer()

        state = self.fresh_db.get_capabilities()
        self.assertNotIn("system_packages", state["installed_stages"])
        mock_packages.assert_not_called()

if __name__ == '__main__':
    unittest.main()
