import logging
from ._version import version as __version__
# from . import main #这里引用main， 在main中引用logger时会发生循环引用。


# dlnaCast package initializer
# 提供包级元数据、日志记录，以及延迟导入常用 API（若子模块存在）

# Export the public-facing names; use "cast" as the public name that maps to the submodule "main".
__all__ = ["__version__", 
            "logger",
            ]

logger = logging.getLogger(__name__)
