import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import sys
import json
import shutil
import tempfile

# Add server directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'server')))

import guga.installer as installer
import guga.cli as cli

class TestGugaInstaller(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for config
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.test_dir, ".guga")
        os.makedirs(self.config_dir)
        
        # Patch CONFIG_DIR and CAPABILITIES_FILE in installer and cli
        self.old_config_dir_inst = installer.CONFIG_DIR
        self.old_cap_file_inst = installer.CAPABILITIES_FILE
        installer.CONFIG_DIR = self.config_dir
        installer.CAPABILITIES_FILE = os.path.join(self.config_dir, "capabilities.json")
        
        self.old_config_dir_cli = cli.CONFIG_DIR
        self.old_cap_file_cli = cli.CAPABILITIES_FILE
        cli.CONFIG_DIR = self.config_dir
        cli.CAPABILITIES_FILE = os.path.join(self.config_dir, "capabilities.json")

    def tearDown(self):
        # Restore constants
        installer.CONFIG_DIR = self.old_config_dir_inst
        installer.CAPABILITIES_FILE = self.old_cap_file_inst
        cli.CONFIG_DIR = self.old_config_dir_cli
        cli.CAPABILITIES_FILE = self.old_cap_file_cli
        # Cleanup
        shutil.rmtree(self.test_dir)

    @patch('guga.installer.is_root')
    @patch('guga.installer.ask')
    @patch('guga.installer.install_linux_packages')
    @patch('guga.installer.setup_man_page')
    @patch('guga.installer.install_systemd_service')
    @patch('guga.installer.shutil.which')
    @patch('guga.installer.platform.system')
    def test_default_installation(self, mock_platform, mock_which, mock_systemd, mock_man, mock_packages, mock_ask, mock_root):
        """1. Test a default installation (Standard Service, Root)"""
        mock_root.return_value = True
        mock_platform.return_value = "Linux"
        mock_which.return_value = "/usr/bin/something"
        
        # Responses: 1 (LAN), n (No OS notif), 1 (Standard Service)
        mock_ask.side_effect = ["1", "n", "1"]
        
        installer.run_system_installer()
        
        # Verify capabilities
        state = installer.load_capabilities()
        self.assertIn("system_packages", state["installed_stages"])
        self.assertIn("systemd_service", state["installed_stages"])
        self.assertTrue(state["capabilities"].get("background_service"))
        
        # Verify sudo functions were called
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
    def test_foreground_only_installation(self, mock_platform, mock_which, mock_systemd, mock_man, mock_cloudflared, mock_packages, mock_ask, mock_root):
        """2. Test a foreground only installation (Internet Mode)"""
        mock_root.return_value = True
        mock_platform.return_value = "Linux"
        mock_which.return_value = "/usr/bin/something"
        
        # Responses: 2 (Public), n (No OS notif), 2 (Foreground Only)
        mock_ask.side_effect = ["2", "n", "2"]
        
        installer.run_system_installer()
        
        # Verify capabilities
        state = installer.load_capabilities()
        self.assertIn("cloudflared", state["installed_stages"])
        self.assertIn("system_packages", state["installed_stages"])
        # Systemd should NOT be in installed_stages or capabilities
        self.assertNotIn("systemd_service", state["installed_stages"])
        self.assertFalse(state["capabilities"].get("background_service"))
        
        # Verify calls
        mock_cloudflared.assert_called_once()
        mock_systemd.assert_not_called()

    @patch('sys.stdout', new_callable=MagicMock)
    def test_cli_warning_when_stages_missing(self, mock_stdout):
        """3. Test a installation where many stages are missing, then check whether the guga.cli works fine or not"""
        # Create an empty capabilities file (no stages installed)
        with open(installer.CAPABILITIES_FILE, "w") as f:
            json.dump({"installed_stages": [], "capabilities": {}}, f)
            
        # Mock args for CLI
        mock_args = MagicMock()
        mock_args.install_service = False
        mock_args.uninstall = False
        mock_args.version = False
        mock_args.status = False
        
        cli.check_capabilities(mock_args)
        
        # Check if warning was printed to stdout
        output = "".join(call.args[0] for call in mock_stdout.write.call_args_list)
        self.assertIn("GuGa hasn't been fully initialized", output)
        self.assertIn("guga --install-service", output)

    @patch('guga.installer.is_root')
    @patch('guga.installer.ask')
    @patch('guga.installer.platform.system')
    @patch('guga.installer.install_linux_packages')
    def test_sudo_skipping(self, mock_packages, mock_platform, mock_ask, mock_root):
        """Verify that sudo stages are skipped when not root."""
        mock_root.return_value = False
        mock_platform.return_value = "Linux"
        mock_ask.side_effect = ["1", "n", "1"]
        
        installer.run_system_installer()
        
        # Verify system_packages stage is NOT in installed_stages
        state = installer.load_capabilities()
        self.assertNotIn("system_packages", state["installed_stages"])
        mock_packages.assert_not_called()

if __name__ == '__main__':
    unittest.main()
