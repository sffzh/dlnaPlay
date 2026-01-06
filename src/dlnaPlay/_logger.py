import logging
import logging.config
from pathlib import Path
from enum import IntEnum

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
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
            "filename": "logs/app.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "level": "DEBUG"
        }
    },

    "root": {
        "handlers": ["console", "file"],
        "level": "DEBUG"
    }
}

class Level(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING

def get_root_level():
    level = LOGGING_CONFIG["root"]["level"]
    try: 
        return Level[str(level).upper()]
    except KeyError:
        logging.warning(f'level in config is Unkown:[{level}]')
        return Level.DEBUG

# 文件路径有效则设置，无效（父目录不存在或指定路径为目录而非文件）则禁用文件日志。
def set_log_file(path:Path):
    if path.parent.exists() and not path.is_dir():
        LOGGING_CONFIG["handlers"]["file"]["filename"] = path.as_posix()
    else:
        disable_log_file()
def disable_log_file():
    del LOGGING_CONFIG["handlers"]["file"]
def set_root_level(level:Level):
    LOGGING_CONFIG["root"]["level"] = level.name

# 在调用setup_loggin完成初始化之前输出的日志，均使用此方法进行输出
def debug(str):
    logging.debug(str)

def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)
    logging.debug(f"logging_config: \n {LOGGING_CONFIG}")

def get_logger(name = None):
    if name: 
        return logging.getLogger(name)
    else:
        # 对模块的import语句不要放在全局区域，以免与__init__.py循环依赖。
        from dlnaPlay import __name__ as app_name
        return logging.getLogger(app_name)