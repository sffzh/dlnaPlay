import time
import sys, os, signal
from pathlib import Path
from typing import Optional
import threading
from queue import Queue
import atexit

import requests
# from upnpclient import Device# pip install upnpclient
import urllib.parse as urllibparse

from dlnaPlay import streaming
from dlnaPlay.args_parser import Args
from dlnaPlay.scan import scan_devices, SCAN_END_FLAG
from dlnaPlay.upnp_controller import Device, DLNADevice
# from . import upnp_controller as upnp
from dlnaPlay._logger import get_logger
logger = get_logger()
config_dir:Path = Path.home() / '.dlna_m3u_list_player'

def pid_file_path(dlnaDevice:DLNADevice)->Path:
    
    # Ensure the config directory exists before generating the pid file path
    config_dir.mkdir(parents=True, exist_ok=True)
    # Fallback to a safe name if device friendly name is None or empty
    safe_name = dlnaDevice.friendly_name
    pid_file = config_dir / f'{safe_name}_player.pid'
    return pid_file

# 开始播放前，写入PID文件，以便外部程序可以通过该文件获取当前播放进程的PID，从而实现控制功能（如停止播放）。
def _write_pid_file(device:DLNADevice):
    pid_file = pid_file_path(device)

    # 注册退出时删除PID文件的函数
    atexit.register(remove_pid_file, pid_file)

    # 捕获终止信号，确保在收到信号时删除PID文件
    def handle_exit_signal(signum, frame):
        device.stop_playing()
        device.wait_until_free()
        streaming.stop_server()
        logger.info('streaming server stopped.')
        remove_pid_file(pid_file)
        logger.info('pid file removed. Now exiting.')
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit_signal)
    signal.signal(signal.SIGINT, handle_exit_signal)

    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.debug(f'Wrote PID {os.getpid()} to file: {pid_file}')
    except Exception as e:
        logger.error(f'Error writing PID file {pid_file}: {e}')

def kill_old_pid(pid_file:Path):
    if pid_file.exists():
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        # 检查进程是否存在，不存在则删除PID文件
        try:
            os.kill(pid, 0)  # 检查进程是否存在
        except ProcessLookupError:
            pid_file.unlink()  # 删除PID文件
            logger.info(f'旧进程未在运行，将清理pid文件: {pid_file}')
            return
        except PermissionError:
            logger.error(f'没有权限检查旧进程， PID: {pid}.')
            return

        try:
            logger.debug(f'Read PID {pid} from file: {pid_file}')
            os.kill(pid, signal.SIGTERM)  # 发送终止信号
            logger.info(f'Sent termination signal to PID {pid}')
        except Exception as e:
            logger.error(f'Error stopping playback using PID file {pid_file}: {e}')
    else:
        logger.warning(f'PID file does not exist: {pid_file}')

# 播放结束后，删除PID文件。
def remove_pid_file(pid_file:Path):
    try:
        if pid_file.exists():
            pid_file.unlink()
            logger.debug(f'Removed PID file: {pid_file}')

        #判断父目录为空，则删除父目录
        parent_dir = pid_file.parent
        if parent_dir.exists() and not any(parent_dir.iterdir()):
            parent_dir.rmdir()
            logger.debug(f'Removed empty pid parent directory: {parent_dir}')

    except Exception as e:
        logger.error(f'Error removing PID file {pid_file}: {e}')

# 同步处理：扫描局域网设备,打印信息到终端。
# 扫描达到超时时长、或者发现匹配搜索词的设备名称时都会停止扫描并返回。
def list_devices(timeout:float, localhost, search_name:str, show_more_info:bool=False):
    logger.info("开始阻塞性查询设备列表....")
    queue = Queue()
    if timeout <= 0: timeout = 5
    thread = threading.Thread(target=scan_devices, args=(queue, timeout, localhost), daemon=True)
    thread.start()

    def handle_exit_signal(signum, frame):
        print("用户手动停止扫描。")
        logger.info("用户手动停止扫描。")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, handle_exit_signal)
    signal.signal(signal.SIGINT, handle_exit_signal)

    while True:
        location = queue.get()
        if location == SCAN_END_FLAG:
            print("到达超时时长，扫描结束")
            break
        
        device = DLNADevice(Device(location))
        _save_location_cache(device)
        print(f" - 查找到DLNA播放设备: [{device.friendly_name}];\n    > location: {location}\n")
        if show_more_info: 
            print(f"    > device_info: {device.__dict__}\n ------------\n")
        if search_name and  search_name in device.friendly_name:
            print(f"此设备名称符合搜索条件[{search_name}]，将停止搜索并退出程序。")
            logger.info("发现符合搜索条件的设备，程序退出。")
            sys.exit(0)

# 获取 dlna 设备的 location 地址。
# 如果不提供 search_name,则返回局域网中发现的第一个设备；
# 如果提供了 search_name，优先从本地缓存文件中匹配；如果存在可匹配缓存项，且其location地址
# 可访问，则响应此设备；否则通过局域网广播进行搜索第一个可匹配设备。
# 参数中提供的 timeout 用来限定单次扫描的超时时间。如果提前发现匹配设备，会直接返回
# 如果单次扫描未发现设备，会自动将超时时间增加2秒后再次搜索；直到超时时间达到20s仍未发现
# 可匹配设备，则放弃任务并退出。
def discover_device(search_name:str, timeout:float=5, host=None, no_cache=False , no_check_location = False) -> Optional[DLNADevice]:
    # 先尝试从缓存文件中获取 location 地址
    if search_name and not no_cache:
        cached_location, location_file = _get_device_location_from_cache(search_name)
        if location_file and (no_check_location or _url_ok(cached_location)):
            return DLNADevice.from_location(cached_location)
        else:
            logger.warning(' * Cached location is invalid [content:%s], will re-discover device', cached_location)
      
    logger.info('Discovering UPnP devices (timeout=%s s)...', timeout)

    queue = Queue()
    thread = threading.Thread(target=scan_devices, args=(queue, timeout, host), daemon=True)
    thread.start()

    while True:
        location = queue.get()
        if location == SCAN_END_FLAG:
            if timeout >= 20: # 完全超时，放弃任务
                logger.warning('No UPnP devices found after extended search.')
                return None
            else:
                logger.warning('No UPnP devices found, retrying with longer timeout...')
                return discover_device(search_name, timeout + 3, host, True)
        else:
            device = DLNADevice(Device(location))
            _save_location_cache(device)
            if not search_name or search_name in device.friendly_name:
                threading.Thread(target=_save_location_cache_from_queue, args=(queue,), daemon=True).start()
                return device

def _save_location_cache(device:DLNADevice):
    location_cache = pid_file_path(device).with_suffix(".location")
    try:
        with open(location_cache, 'w') as f:
            f.write(device.location)
    except Exception as e:
        logger.warning('save_location_cache failed: ',e)

def _save_location_cache_from_queue(queue:Queue):
    while True:
        location = queue.get()
        if location == "TIMEOUT":
            break
        _save_location_cache(DLNADevice.from_location(location))

def _url_ok(url, timeout=5):
    if not url: return False
    try:
        r = requests.head(url, timeout=timeout)
        return r.status_code < 400
    except requests.RequestException: return False

def _get_device_location_from_cache(search_name:str):
    # 遍历缓存文件夹下的location文件，查找包含指定名称的location地址
    location_files = config_dir.glob('*.location')
    for location_file in location_files:
        cached_name = location_file.name[:-len('_player.location')]
        print(f'Checking cached device name: [{cached_name}] for search name: [{search_name}]')
        if search_name not in cached_name:
            continue
        try:
            with open(location_file, 'r') as f:
                location = f.read().strip()
            logger.info(f'Read device location from cache: {location_file} -> {location}')
            return location, location_file
        except Exception as e:
            logger.error(f'Error reading location cache file {location_file}: {e}')
    return None, None

def get_songs_from_m3u(m3u_path: Path):
    songs = []
    try:
        with open(m3u_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # 歌曲文件的实际路径为相对于M3U文件的路径
                    if not line.startswith("/"):
                        line = (m3u_path.parent / line).resolve()
                    if Path(line).exists():
                        songs.append(line)
    except Exception as e:
        print(f'Error reading M3U file: {e}')
    return songs

def filter_aviable_songs(media_files:list):
    return [song for song in media_files if Path(song).exists()]

def play_songs(device:DLNADevice, songs: list, localhost = None, serve_port=0, target_volume:int=0):
    if not device:
        print('No devices to play on.')
        return

    if not songs:
        print('No songs to play.')
        return
    
    logger.info('Playing [%d] songs on device[%s]', len(songs), device.friendly_name)
    logger.debug('target device loaction: %s', device.location)

    if localhost:
        serve_ip = localhost
    else:
        url_parse = urllibparse.urlparse(device.location)
        target_ip = url_parse.hostname
        serve_ip = streaming.get_serve_ip(target_ip)
    
    if not serve_port or serve_port <= 0:
        serve_port = streaming.find_free_port(serve_ip)
        logger.info(f'Auto-selected free port {serve_port} for streaming server.')

    files_urls, _, server_thread = streaming.start_server(songs, serve_ip, serve_port)
    
    for song in songs:
        song=Path(song)
        if not song.exists():
            logger.info(f'Song file does not exist: {song}')
            continue
        url = files_urls.get(song.name)
        if url: 
            logger.info(f'Playing song: {song} -> {url}')

            device.play(url)

            logger.info('Waiting for song to finish...')

            # 给设备一点时间开始播放，加上调整音量用的时间，总等待时间不长于20秒
            device.wait_until_play(5, 20)
            # 等待设备空闲。注意即使最后一首也要等播放完成再停止服务器
            device.wait_until_free(0, 3)

            # 播放下一曲前先调整音量，如果当前音量小于目标音量，每首歌音量加10。
            if target_volume > 0:
                device.step_volume(10, target_volume)

    logger.info('All songs have been played.')
    streaming.stop_server()  # 停止服务器
    if server_thread:
        logger.debug(f'Waiting for server thread to finish...')
        server_thread.join()  # type: ignore # 等待服务器线程结束

def play_with_media_url(device:DLNADevice, url:str):
    logger.info('Playing stream url on device[%s], \n    - url:{%s}', device.friendly_name, url)
    device.play(url)


# 弃用：在 Sound SE音箱上只要更改音量，就会停止播放，原因暂不明。
def volume_fade_in_threaded(device:DLNADevice, start_volume:int, 
                            target_volume:int, step:int=5, delay:float=0.5):
    # 初始音量设为start_volume
    device.set_volume(start_volume)
    thread = threading.Thread(target=lambda:device.volume_fade_in(target_volume , step, delay, start_volume) 
                              , daemon=True)
    thread.start()
    logger.info('Started volume fade-in thread.')
    return thread

def cleanup_temp_files():

    if not config_dir.exists():
        logger.info('No temporary files to clean up.')
        return

    pid_files = list(config_dir.glob('*_player.pid'))
    location_files = list(config_dir.glob('*.location'))

    for pid_file in pid_files:
        try:
            kill_old_pid(pid_file)
            pid_file.unlink()
            logger.info(f'Removed PID file: {pid_file}')
        except Exception as e:
            logger.error(f'Error removing PID file {pid_file}: {e}')

    for loc_file in location_files:
        try:
            # 清理目录时不用停止播放设备，因为可能设备实例正在做的事与本程序无关
            # stop_device_playing(Device(loc_file.read_text().strip()))
            loc_file.unlink()
            logger.info(f'Removed location cache file: {loc_file}')
        except Exception as e:
            logger.error(f'Error removing location cache file {loc_file}: {e}')

    # 如果目录为空，删除目录
    try:
        if not any(config_dir.iterdir()):
            config_dir.rmdir()
            logger.info(f'Removed empty config directory: {config_dir}')
    except Exception as e:
        logger.error(f'Error removing config directory {config_dir}: {e}')

def _show_watch_help():
    print('''
    -w 参数用来查询设备状态。用法： dlnaPlay -w <tag>
    例如： `dlnaPlay -w device_info -d Speaker8957`
    可以查看局域网upnp设备 Speaker8957 的信息。
    tag 的可选值见 dlnaPlay -h 中的列举列。以下为部分tag的说明：
          * volume : 查看当前指定设备的音量
          * device_info : 查看当前设备的详情(包含location、friendly_name等)
          * device_state : 当前设备的播放状态
          * current_pid : 当前正在播放的进程PID
          * help : 输出此说明。
          * set_volume : 调整设备音量。目标音量由参数 --volume 设值。
                          示例： dlnaPlay -w set_volume -v 32
''')

# 不影响播放的情况下查看播放设备的信息。
# 注意此函数可能有调用 DLNADevice 类封装的方法以外的UpnpClient.Device的Actions。
def show_info(device:DLNADevice, args:Args):
    watch:set = args.watch
    if not watch:
        return
    logger.info(f'args.watch items:{watch}')
    for item in watch:
        item = item.lower()
        if item == 'volume':
            # 使用device 获取设备音量
            rc = device.device.RenderingControl
            volume_info = device.get_volume()
            print(f" channels: {rc}")
            print(f' Volume info: {volume_info}')
        elif item == "device_info":
            print(f" device info: {device.device.__dict__}")
        elif item == 'device_state':
            # 获取 AVTransport 服务 
            avt = device.device.AVTransport # 调用 GetTransportInfo 获取播放状态 
            info = avt.GetTransportInfo(InstanceID=0) 
            print(" 播放状态:", info) 
            # 获取当前媒体信息 
            media_info = avt.GetMediaInfo(InstanceID=0) 
            print(" 媒体信息:", media_info) 
            # 获取当前播放进度 
            position = avt.GetPositionInfo(InstanceID=0) 
            print(" 播放进度:", position)
            
        elif item == 'current_pid':
            pid_files = list(config_dir.glob('*_player.pid'))
            if  not  pid_files:
                print("no pid_files found.")
            for pid_file in pid_files:
                try:
                    with open(pid_file, 'r') as f:
                        pid = f.read().strip()
                    print(f'PID file: {pid_file}, PID: {pid}')
                except Exception as e:
                    logger.error(f'Error reading PID file {pid_file}: {e}')
        
        elif item == "set_volume":
            device.set_volume(args.volume)
        else:
            print(f'~ Unknown watch item: {item}')
    sys.exit(0)

# main_func: stop_playing
# device 类型为 DLNADevice
def stop_device_playing(device: Optional[DLNADevice], device_query:str):
    # 所有选中的设备都发送停止命令。如果没有查询到设备，但PID文件存在，
    # 在杀进程后设备会继续播放，直到缓存到头，表现为再播放一会儿后自动停止。
    if device: device.stop_playing()
    
    if device_query:
        if device:
            pid_file = pid_file_path(device)
            kill_old_pid(pid_file)
        else:
            logger.warning('No matching UPnP devices found to stop.')
    else: # 停止所有已知设备的播放
        # 遍历home目录下所有的pid文件，发信号停止对应的播放行为
        pid_files = config_dir.glob('*_player.pid')
        for pid_file in pid_files:
            kill_old_pid(pid_file)

# 根据入参整理需要播放的音乐列表
# 实际需要的参数是 media_files / list_file / shuffle_songs / max_songs
def _manage_songs_list(args:Args, max_songs:int = 20) -> list:
    songs = []
    if args.media_files:
        songs = filter_aviable_songs(args.media_files)

    if args.list_file:
        songs.extend(get_songs_from_m3u(args.list_file))

    if args.shuffle_songs:
        import random
        random.shuffle(songs)
        logger.info('Shuffled the song list for random playback.')
    
    max_songs = args.max_songs or max_songs
    if len(songs) > max_songs:
        songs = songs[:max_songs]  # 只取前max_songs首歌，避免播放时间过长

    return songs

# 开始播放前初始化音量
def _init_start_volume(device:DLNADevice, origin_volume:int, volume_target:int, volume_start:int = -1):
    if volume_start >= 0 and volume_start < volume_target:
        # 先调低音量，以实现渐变淡入。
        device.set_volume(volume_start)
        # set_volume(device, args.volume_start) 
    elif volume_target > 0 and origin_volume != volume_target:
        device.set_volume(volume_target)

def main():
    args = Args.resolveArgs()

    # 清理临时文件逻辑
    if args.cleanup:
        cleanup_temp_files()
        return 0

    if args.need_help_watch():
        _show_watch_help()
        return 0

    # 查询 device 列表逻辑
    if args.list_devices:
        list_devices(args.timeout or 5, args.localhost or None, args.device_query, args.is_debug)
        return 0

    if args.location:
        device = DLNADevice.from_location(args.location)
    else:
        device = discover_device(args.device_query, timeout=args.timeout, host=args.localhost or None)

    # 停止播放逻辑
    if args.stop_playing:
        stop_device_playing(device, args.device_query)
        return 0

    # 以下逻辑都要求 device不为空。
    if not device:
        logger.warning('No matching UPnP devices found.')
        return 1
    
    if args.watch: show_info(device, args)
        

    # 播放音乐逻辑
    #获取原始音量,以便恢复
    original_volume = device.get_volume('获取初始音量失败，播放结束后将无法重置音量')

    try:
        _write_pid_file(device)
        if args.url:
            _init_start_volume(device, original_volume, args.volume)
            device.play(args.url)
            #至少等待30再退出
            device.wait_until_play(5, 30)
            device.wait_until_free(0, 5)
        else:
            _init_start_volume(device, original_volume, args.volume, args.volume_start)
            # 以下逻辑都要求songs不为空
            songs = _manage_songs_list(args, 20)
            if not songs:
                logger.error("songs list are empty, or all file path not aviable.")
                return 1

            play_songs(device, songs, args.localhost, args.serve_port, args.volume)
    except:
        logger.exception('主流程错误：未能完成播放')
    finally:
        # 确保播放结束后删除PID文件
        remove_pid_file(pid_file_path(device))
        # 恢复播放前的设备音量
        if original_volume >=0:
            device.set_volume(original_volume)

    logger.info('Playback finished. Exiting.')

    return 0


if __name__ == '__main__':
    sys.exit(main())