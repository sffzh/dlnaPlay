from argparse import ArgumentParser,Namespace
from pathlib import Path
import sys
import itertools
from dlnaPlay import logger
from dlnaPlay.logging_config import Level, set_root_level, set_log_file, setup_logging, get_root_level

class Args:
    def __init__(self, args:Namespace):
        self.localhost:str = args.host
        self.timeout:float = args.timeout
        self.list_file:Path = args.list_file
        self.log_file:Path = args.log
        self.media_files:list[Path] = args.media
        self.device_query:str = args.device_query
        self.serve_port:int = args.serve_port
        self.volume:int = args.volume
        self.volume_start:int = args.volume_start
        self.max_songs:int = args.max_songs if hasattr(args, 'max_songs') and args.max_songs >= 0 else 0
        self.is_debug:bool = args.debug
        self.shuffle_songs:bool = args.shuffle
        self.stop_playing:bool = args.stop
        self.cleanup:bool = args.cleanup
        self.watch:list[str] = list(itertools.chain.from_iterable(args.watch)) if  args.watch else [] 

        self.__dict__.update(vars(args))

        try:
            if self.is_debug:
                set_root_level(Level.DEBUG)
            else:
                set_root_level(Level.INFO)

            if self.log_file:
                set_log_file(self.log_file)
        finally:
            setup_logging()
        
        if get_root_level() is Level.DEBUG:
            logger.debug("Debug logging will be enabled.")

        if not self.stop_playing and not self.list_file and not self.media_files and not self.cleanup and not self.watch:
            print("List file( -f <list_file_path>) is required unless stopping playback.\n" \
            "use `-h` option to check useage.")
            sys.exit(2)

def resolveArgs()->Args:
    parser = ArgumentParser(description="""
探测局域网中的DLNA播放设备，并使用入参指定的歌单文件进行随机播放。
""")
    ## 注意 -h 和 --help 已被 argparse 默认占用显示帮助信息，不能再用作其它参数。
    parser.add_argument( '-t', '--timeout', default=5.0, type=float, 
                        help='''SSDP探测超时时间，单位秒，默认3秒。''')
    parser.add_argument( '-f', '--list_file', '--m3u', '--m3u8', type=Path, 
                        help='''[必须]播放列表文件，通常为m3u或m3u8格式的文件。''')
    parser.add_argument('-m', '--media', default=[], type=Path, action="append",
                        help='''指定要播放的媒体文件。可重复使用此参数指定多个文件。
                        如果不打乱顺序，--list_file参数 指定的文件排列在前。
                        ''')
    parser.add_argument( '-p', '--serve_port','--port', default=0, type=int,
                        help='''流媒体服务器端口，默认0（自动选择）。''')
    parser.add_argument( '-v', '--volume', default=30, type=int,
                        help='''音量大小，范围0-100，默认30。''')
    parser.add_argument( '-vs', '--volume_start', default=-1, type=int,
                    help='''淡入音量大小，范围0-100，默认-1， 小于0时不执行淡入。''')
    parser.add_argument( '-d', '--device_query', '-q', '--query', '--device', default=None, type=str,
                        help='''设备名称查询字符串，用于指定特定的播放设备。
                        如果不指定，则使用第一个发现的设备。
                        如果查询结果有多个，则选择第一个匹配的设备。
                        如果没有找到匹配的设备，会增加超时时间重新探测，直到找到设备或超时过长。''')
    parser.add_argument( '-s','--shuffle', action='store_true',
                        help='''启用随机播放模式，打乱播放列表顺序。''')
    parser.add_argument( '-c', '--cleanup', action='store_true',
                        help='''清理本程序产生的临时文件及文件夹，包含PID文件，location地址缓存文件等。''')
    parser.add_argument( '-w', '--watch', nargs='+', default=[], 
                        help='''查看部分参数状态。可多次使用此参数查看多个状态。
                        可选值包括：volume, device_state, current_pid''')
    parser.add_argument('-l', '--log', '--log_file', default=None, type=Path,
                        help='''日志文件地址。可不指定。如果为空，不会输出到文件。文件的父目录
                         必须是已经存在的。文件如果不存在将自动创建。''')
    parser.add_argument( '-H', '--host', '--localhost', default=None, type=str, 
                        help='''本机host地址，用于多网卡环境下指定局域网网卡。不指定时使用"0.0.0.0".
                        通常情况下不指定即可。
                        ''')
    parser.add_argument( '-M', '--max_songs', '--max', default=20, type=int,
                        help='''最大播放歌曲数量，默认20。值为0时采用20。''') 
    parser.add_argument( '-S','--stop', '--stop_playing', action='store_true',
                        help='''停止当前播放的歌曲。''')
    parser.add_argument( '-D', '--debug', '--test', action='store_true',
                        help='''启用调试模式，输出更多日志信息。''')
    return Args(parser.parse_args()) 

if __name__ == '__main__':
    args = resolveArgs()
    print(f"args_data: {args.__dict__}")