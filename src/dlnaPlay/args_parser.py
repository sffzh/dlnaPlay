from argparse import ArgumentParser
from pathlib import Path
import sys
from dataclasses import dataclass
from dlnaPlay._logger import get_logger, LOGGING_CONFIG, Level
logger = get_logger('Args_Parser')

@dataclass
class Args:
    localhost:str
    timeout:float
    list_file:Path
    log_file:Path
    media_files:list
    device_query:str
    serve_port:int
    volume:int
    volume_start:int
    max_songs:int
    is_debug:bool
    shuffle_songs:bool
    stop_playing:bool
    cleanup:bool
    watch:set
    show_version:bool
    list_devices:bool
    location:str

    # 由dataclass支持的方法，会在对象初始化后被调用。
    def __post_init__(self):
        try:
            if self.is_debug:
                LOGGING_CONFIG.enable_debug()
            else:
                LOGGING_CONFIG.set_root_level(Level.INFO)

            if self.log_file:
                LOGGING_CONFIG.set_log_file(self.log_file)
        finally:
            LOGGING_CONFIG.setup_logging()
            
        # 兼容旧参数写法：
        if self.watch and 'list_devices' in self.watch:
            self.list_devices = True
        
        if LOGGING_CONFIG.is_debug_enabled():
            logger.debug("Debug logging will be enabled.")

        if self.show_version:
            # 对模块的import语句不要放在全局区域，以免与__init__.py循环依赖。
            from dlnaPlay import __version__
            print(__version__)
            sys.exit(0)

    def need_help_watch(self)->bool:
        return True if self.watch and 'help' in self.watch else False

    @staticmethod
    def resolveArgs():
        parser = ArgumentParser(description="""
    探测局域网中的DLNA播放设备，并使用入参指定的歌单文件进行随机播放。
    """)
        ## 注意 -h 和 --help 已被 argparse 默认占用显示帮助信息，不能再用作其它参数。
        parser.add_argument( '-t', '--timeout', default=5.0, type=float, 
                            help='''SSDP探测超时时间，单位秒，默认3秒。''')
        parser.add_argument( '-f', '--list_file', '--m3u', '--m3u8', type=Path, 
                            help='''[必须]播放列表文件，通常为m3u或m3u8格式的文件。''')
        parser.add_argument('-m', '--media_files', '--media', default=[], type=Path, action="append",
                            help='''指定要播放的媒体文件。可重复使用此参数指定多个文件。
                            如果不打乱顺序，--list_file参数 指定的文件排列在前。
                            ''')
        parser.add_argument( '-p', '--serve_port','--port', default=0, type=int,
                            help='''流媒体服务器端口，默认0（自动选择）。''')
        parser.add_argument( '-v', '--volume', default=0, type=int,
                            help='''音量大小，范围0-100，默认不设置（使用设备当前音量）。''')
        parser.add_argument( '-vs', '--volume_start', default=-1, type=int,
                        help='''淡入音量大小，范围0-100，默认-1， 小于0或不小于volume时不执行淡入。''')
        parser.add_argument( '-d', '--device_query', '-q', '--query', '--device', default=None,
                            type=str, help='''设备名称查询字符串，用于指定特定的播放设备。
                            如果不指定，则使用第一个发现的设备。
                            如果查询结果有多个，则选择第一个匹配的设备。
                            如果没有找到匹配的设备，会增加超时时间重新探测，直到找到设备或超时过长。''')
        parser.add_argument( '-s', '--shuffle_songs','--shuffle', action='store_true',
                            help='''启用随机播放模式，打乱播放列表顺序。''')
        parser.add_argument( '-w', '--watch', nargs='+', default=set(), type=str,
                            help='''查看部分参数状态。可多次使用此参数查看多个状态。\r\n
                            可选值包括：volume, device_state, current_pid, help. 
                            可以使用`-w help`来查看`-w`选项的详细说明
                            '''
                            )
        parser.add_argument('-l', '--log_file', '--log',  default=None, type=Path,
                            help='''日志文件地址。可不指定。如果为空，不会输出到文件。文件的父目录
                            必须是已经存在的。文件如果不存在将自动创建。''')
        
        parser.add_argument('--location', default=None, type=str,
                            help='''直接指定upnp设备的location地址。不进行搜寻也不看缓存''')
        
        parser.add_argument( '-H', '--localhost', '--host',  default=None, type=str, 
                            help='''本机host地址，用于多网卡环境下指定局域网网卡。不指定时使用"0.0.0.0".
                            通常情况下不指定即可。
                            ''')
        parser.add_argument( '-M', '--max_songs', '--max', default=20, type=int,
                            help='''最大播放歌曲数量，默认20。值为0时采用20。''') 
        parser.add_argument('-L', '--list_devices', '--list', '--devices', action="store_true",
                            help='''扫描并列出局域网中的设备列表。可用-d指定搜寻字符串，扫描达到超时时间
                            或发现符合条件的设备都会停止扫描行为。'''
                            )
        parser.add_argument( '-S', '--stop_playing', '--stop', action='store_true',
                            help='''停止当前播放的歌曲。''')
        parser.add_argument( '-C', '--cleanup', action='store_true',
                            help='''清理本程序产生的临时文件及文件夹，包含PID文件，location地址缓存文件等。''')
        parser.add_argument( '-D', '--is_debug','--debug', '--test', action='store_true',
                            help='''启用调试模式，输出更多日志信息。''')
        parser.add_argument( '-V', '--show_version', '--version', '--ver', action='store_true',
                            help='''输出版本号信息''')
        return Args(**vars(parser.parse_args())) 

def resolveArgs()->Args:
    return Args.resolveArgs()

if __name__ == '__main__':
    args = Args.resolveArgs()
    print(f"args_data: {args.__dict__}")