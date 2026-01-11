from ._version import version as __version__
from .scan import scan_devices
from .streaming import start_server, stop_server
from .soap import SOAP
from .upnp_controller import Device, Action, Service
from .upnp_parser import UPnPDevice, UPnPService
from .main import discover_device, list_devices, play_songs, stop_device_playing, show_info, cleanup_temp_files
# _version.py 会由打包插件自动生成。

# dlnaCast package initializer
# 提供包级元数据、日志记录，以及延迟导入常用 API（若子模块存在）

# Export the public-facing names; use "cast" as the public name that maps to the submodule "main".
__all__ = ["__version__", 
           "SOAP",
           "Device", "Action", "Service",
           "UPnPDevice", "UPnPService",
           "scan_devices", "start_server", "stop_server",
           "discover_device", "list_devices", "play_songs", "stop_device_playing", "show_info", "cleanup_temp_files"
           ]



