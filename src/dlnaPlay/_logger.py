import logging
import logging.config
from dataclasses import dataclass
from pathlib import Path
from enum import IntEnum

# 用于构造默认的日志文件名。
APP_NAME="dlnaPlay"


class Level(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING

@dataclass
class LogConfig:
    log_path: Path
    log_file_disabled: bool
    root_level: Level

    # 拼装dic_config的主要逻辑。
    def get_dict_config(self)->dict:
        if self.log_path and not self.log_file_disabled:
            self.log_path.parent.mkdir(exist_ok=True)

        return {
            "version": 1,
            "disable_existing_loggers": False,

            "formatters": {
                "standard": {
                    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                }, 
                "with_line_num": {
                    "format": "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d: %(message)s"
                }
            },

            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": "DEBUG"
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "filename": f"{self.log_path.as_posix()}",
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "level": "INFO"
                },
                "debug_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "with_line_num",
                    "filename": f"{self.log_path.with_suffix('.debug.log').as_posix()}",
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "level": "DEBUG"
                }
            },

            "root": {
                "handlers": ["console", "file", "debug_file"],
                "level": f"{self.root_level.name}"
            }
        }
    
    def set_log_file(self, path:Path):
        # 文件路径有效则设置，无效（父目录不存在或指定路径为目录而非文件）则禁用文件日志。
        if path.parent.exists() and not path.is_dir():
            self.log_file_disabled = False
            self.log_path = path
        else:
            self.log_file_disabled = True
    def disable_log_file(self):
        self.log_file_disabled = True

    # 配置默认的级别是INFO
    def enable_debug(self):
        self.root_level = Level.DEBUG
        return self
    def is_debug_enabled(self):
        return self.root_level == Level.DEBUG
    def set_root_level(self, level:Level):
        self.root_level = level
    def setup_logging(self):
        logging.config.dictConfig(self.get_dict_config())
        logging.getLogger().debug(f"set up logging with dict config: \n {self.get_dict_config()}")


LOGGING_CONFIG = LogConfig(
    log_path = Path(f"logs/{APP_NAME}.log"),
    log_file_disabled = False,
    root_level= Level.INFO
)

def get_root_level():
    return LOGGING_CONFIG.root_level

# 文件路径有效则设置，无效（父目录不存在或指定路径为目录而非文件）则禁用文件日志。
def set_log_file(path):
    if path:
        LOGGING_CONFIG.set_log_file(path)
    else:
        LOGGING_CONFIG.disable_log_file()

def disable_log_file():
    LOGGING_CONFIG.disable_log_file()

def set_root_level(level:Level):
    LOGGING_CONFIG.root_level = level

# 在调用setup_loggin完成初始化之前输出的日志，均使用此方法进行输出
def debug(str):
    logging.debug(str)

def setup_logging():
    LOGGING_CONFIG.setup_logging()

def get_logger(name = None):
    if name: 
        return logging.getLogger(name)
    else:
        # 对模块的import语句不要放在全局区域，以免与__init__.py循环依赖。
        from dlnaPlay import __name__ as app_name
        return logging.getLogger(app_name)