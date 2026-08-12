from unittest.mock import patch

from neko_launcher.e2e.final_windows_harness import main
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway
from neko_launcher.infrastructure.core.core_control_channel import NamedPipeCoreControlChannel
from neko_launcher.infrastructure.core.core_process import WindowsCoreProcessAdapter
from neko_launcher.infrastructure.process.process_detector import ExactPso2TargetDetector
from neko_launcher.infrastructure.storage.secure_store import KeyringSecureStore


def test_live_composition_imports_and_construction(monkeypatch):
    monkeypatch.setenv("NEKO_LIVE_HOSTED_EXECUTION", "YES-I-UNDERSTAND")
    
    with patch("neko_launcher.e2e.hosted_positive_kp.execute_hosted_positive_and_kp") as mock_execute:
        mock_execute.return_value = {"success": True}
        
        result = main(["execute", "--live"])
        assert result == 0
        mock_execute.assert_called_once()
        
        kwargs = mock_execute.call_args[1]
        gateway = kwargs["gateway"]
        core_process = kwargs["core_process"]
        core_channel = kwargs["core_channel"]
        detector = kwargs["detector"]
        
        assert isinstance(gateway, SupabaseGateway)
        assert isinstance(gateway._auth_storage._secure_store, KeyringSecureStore)
        assert isinstance(core_process, WindowsCoreProcessAdapter)
        assert isinstance(core_channel, NamedPipeCoreControlChannel)
        assert isinstance(detector, ExactPso2TargetDetector)
        
        assert core_process._executable.name == "NekoProxyCore.exe"
        assert core_channel._pipe_name == "NekoProxyCoreControl"
        
        # It binds expected_server_pid to core_process.owned_process_id
        assert core_channel._expected_server_pid == core_process.owned_process_id
