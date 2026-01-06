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
from dlnaPlay.args_parser import resolveArgs
from dlnaPlay.scan import scan_devices, SCAN_END_FLAG
from dlnaPlay.upnp_controller import Device
# from . import upnp_controller as upnp
from dlnaPlay._logger import get_logger
logger = get_logger()
config_dir:Path = Path.home() / '.dlna_m3u_list_player'

def pid_file_path(device_frendly_name: Optional[str])->Path:
    
    # Ensure the config directory exists before generating the pid file path
    config_dir.mkdir(parents=True, exist_ok=True)
    # Fallback to a safe name if device friendly name is None or empty
    safe_name = device_frendly_name or 'unknown_device'
    pid_file = config_dir / f'{safe_name}_player.pid'
    return pid_file

# 开始播放前，写入PID文件，以便外部程序可以通过该文件获取当前播放进程的PID，从而实现控制功能（如停止播放）。
def write_pid_file(device:Device):
    pid_file = pid_file_path(device.friendly_name)

    # 注册退出时删除PID文件的函数
    atexit.register(remove_pid_file, pid_file)

    # 捕获终止信号，确保在收到信号时删除PID文件
    def handle_exit_signal(signum, frame):
        stop_device_playing(device)
        wait_until_device_free(device)
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

# 同步处理：扫描局域网设备
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
        
        device = Device(location)
        save_location_cache(device)
        print(f" - 查找到DLNA播放设备: [{device.friendly_name}];\n    > location: {location}\n")
        if show_more_info: 
            print(f"    > device_info: {device.__dict__}\n ------------\n")
        if search_name and device.friendly_name and  search_name in device.friendly_name:
            print(f"此设备名称符合搜索条件[{search_name}]，将停止搜索并退出程序。")
            logger.info("发现符合搜索条件的设备，程序退出。")
            sys.exit(0)

# 获取 dlna 设备的 location 地址。
def discover_device(search_name:str, timeout:float=5, host=None, no_cache=False):
    # 先尝试从缓存文件中获取 location 地址
    if search_name and not no_cache:
        cached_location, location_file = get_device_location_from_cache(search_name)
        if location_file and url_ok(cached_location):
            return Device(cached_location)
        else:
            logger.warning(f'.Cached location is invalid [content:{cached_location}], will re-discover device')
      
    logger.info(f'Discovering UPnP devices (timeout={timeout}s)...')

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
            device = Device(location)
            save_location_cache(device)
            if not search_name or (device.friendly_name and search_name in device.friendly_name):
                threading.Thread(target=save_location_cache_from_queue, args=(queue,), daemon=True).start()
                return device

def save_location_cache(device:Device):
    location_cache = pid_file_path(device.friendly_name).with_suffix(".location")
    try:
        with open(location_cache, 'w') as f:
            f.write(device.location)
    except Exception as e:
        logger.warning('save_location_cache failed: ',e)

def save_location_cache_from_queue(queue:Queue):
    while True:
        location = queue.get()
        if location == "TIMEOUT":
            break
        device = Device(location)
        save_location_cache(device)

def url_ok(url, timeout=5):
    if not url: return False
    try:
        r = requests.head(url, timeout=timeout)
        return r.status_code < 400
    except requests.RequestException: return False

def get_device_location_from_cache(search_name:str):
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

def play_songs(device:Device, songs: list, localhost = None, serve_port=0, target_volume:int=30):
    if not device:
        print('No devices to play on.')
        return

    if not songs:
        print('No songs to play.')
        return
    
    logger.info(f'Playing {len(songs)} songs on device: {device.location}')


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

    write_pid_file(device)
    
    for song in songs:
        song=Path(song)
        if not song.exists():
            logger.info(f'Song file does not exist: {song}')
            continue
        url = files_urls.get(song.name)
        if url: 
            logger.info(f'Playing song: {song} -> {url}')

            start_playing(device, url)

            logger.info('Waiting for song to finish...')

            # 给设备一点时间开始播放，加上调整音量用的时间，总等待时间不长于20秒
            time.sleep(20)  
            # 等待设备空闲。注意即使最后一首也要等播放完成再停止服务器
            wait_until_device_free(device)

            # 播放下一曲前先调整音量
            current_volume = device.RenderingControl.GetVolume(
                    InstanceID=0,
                    Channel='Master'
                )['CurrentVolume']
            if current_volume < target_volume:
                current_volume = min (current_volume + 10, target_volume)
                set_volume(device, current_volume)

    logger.info('All songs have been played.')
    streaming.stop_server()  # 停止服务器
    if server_thread:
        logger.debug(f'Waiting for server thread to finish...')
        server_thread.join()  # type: ignore # 等待服务器线程结束
        
#函数：判断DLNA设备是否正在播放中
def is_device_free(device:Device) -> bool:
    try:
        av_transport = device.AVTransport
        current_transport_state = av_transport.GetTransportInfo(
            InstanceID=0
        )['CurrentTransportState']
        return current_transport_state == 'PLAYING'
    except Exception as e:
        print(f'Error checking device state: {e}')
        return False

def set_volume(device:Device, volume:int):
    try:
        rendering_control = device.RenderingControl
        rendering_control.SetVolume(
            InstanceID=0,
            Channel='Master',
            DesiredVolume=volume
        )
    except Exception as e:
        print(f'Error setting volume: {e}')

def start_playing(device:Device, url:str, volume:int = 0):
    try:
        av_transport = device.AVTransport

        if volume:
            device.RenderingControl.SetVolume(
                    InstanceID=0,
                    Channel='Master',
                    DesiredVolume=volume
                )

        av_transport.SetAVTransportURI(
            InstanceID=0,
            CurrentURI=url,
            CurrentURIMetaData=''
        )
        av_transport.Play(
            InstanceID=0,
            Speed='1'
        )
    except Exception as e:
        print(f'Error starting playback: {e}')

def volume_fade_in(device:Device, target_volume:int, step:int=5, delay:float=0.5):
    try:
        rendering_control = device.RenderingControl
        current_volume = rendering_control.GetVolume(
            InstanceID=0,
            Channel='Master'
        )['CurrentVolume']
        logger.info(f'Starting volume fade-in from {current_volume} to {target_volume}; step={step}, delay={delay}s')
        while current_volume < target_volume:
            current_volume = min(current_volume + step, target_volume)
            rendering_control.SetVolume(
                InstanceID=0,
                Channel='Master',
                DesiredVolume=current_volume
            )
            # device.AVTransport.Play(InstanceID=0, Speed='1')  # 确保设备在播放状态
            logger.debug(f'Setting volume to {current_volume}')
            time.sleep(delay)
        logger.info(f'Volume fade-in completed. final volume: {current_volume}')
    except Exception as e:
        print(f'Error during volume fade-in: {e}')

# 弃用：在 Sound SE音箱上只要更改音量，就会停止播放，原因暂不明。
def volume_fade_in_threaded(device:Device, start_volume:int, target_volume:int, step:int=5, delay:float=0.5):
    set_volume(device, start_volume)  # 初始音量设为start_volume
    thread = threading.Thread(target=volume_fade_in, args=(device, target_volume, step, delay), daemon=True)
    thread.start()
    logger.info('Started volume fade-in thread.')
    return thread

#函数：等待DLNA设备空闲,默认两秒轮询一次
# 默认最长等待10分钟。一般没有歌曲时长超过10分钟的。
def wait_until_device_free(device:Device, check_interval=2.0, max_wait=600.0):
    import time
    has_waited = 0.0
    logger.info('Waiting for device to become free...')
    state = 'Free'
    while True:
        info = device.AVTransport.GetTransportInfo(InstanceID=0)
        state = info["CurrentTransportState"]
        if state in ("STOPPED", "PAUSED_PLAYBACK", "NO_MEDIA_PRESENT"): 
            break
        logger.debug('Device is currently [%s]. Waiting...', state)
        has_waited += check_interval
        if has_waited > max_wait:
            logger.warning('Max wait time exceeded. Device may still be busy.')
            return has_waited
        time.sleep(check_interval)
    logger.info('Device now is [%s].', state)
    return has_waited

# 发信号给DLNA设备停止播放。
def stop_device_playing(device:Device):
    try:
        av_transport = device.AVTransport
        av_transport.Stop(InstanceID=0)
        logger.info('Sent stop command to device[%s].', device.friendly_name or device.location)
    except Exception as e:
        logger.error(f'Error stopping playback: {e}')

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

# 不影响播放的情况下查看播放设备的信息。
def show_info(device:Device, watch:set):
    if not watch:
        return
    logger.info(f'args.watch items:{watch}')
    for item in watch:
        item = item.lower()
        if item == 'volume':
            # 使用device 获取设备音量
            rc = device.RenderingControl
            volume_info = rc.GetVolume(InstanceID=0, Channel='Master')
            print(f" channels: {rc}")
            print(f' Volume info: {volume_info}')
        elif item == "device_info":
            print(f" device info: {device.__dict__}")
        elif item == 'device_state':
            # 获取 AVTransport 服务 
            avt = device.AVTransport # 调用 GetTransportInfo 获取播放状态 
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
        else:
            print(f'~ Unknown watch item: {item}')
    sys.exit(0)

# main_func: stop_playing
def stop_playing(device, device_query:str):
    # 所有选中的设备都发送停止命令。如果没有查询到设备，但PID文件存在，
    # 在杀进程后设备会继续播放，直到缓存到头，表现为再播放一会儿后自动停止。
    if device: stop_device_playing(device)
    
    if device_query:
        if device:
            pid_file = pid_file_path(device.friendly_name)
            kill_old_pid(pid_file)
        else:
            logger.warning('No matching UPnP devices found to stop.')
    else: # 停止所有已知设备的播放
        # 遍历home目录下所有的pid文件，发信号停止对应的播放行为
        pid_files = config_dir.glob('*_player.pid')
        for pid_file in pid_files:
            kill_old_pid(pid_file)    

def main():
    args = resolveArgs()

    # 清理临时文件逻辑
    if args.cleanup:
        cleanup_temp_files()
        return 0

    
    # 查询 device 列表逻辑
    if args.list_devices:
        list_devices(args.timeout or 5, args.localhost or None, args.device_query, args.is_debug)
        return 0

    device = discover_device(args.device_query, timeout=args.timeout, host=args.localhost or None)

    # 停止播放逻辑
    if args.stop_playing:
        stop_playing(device, args.device_query)
        return 0
    
    # 以下逻辑都要求 device不为空。
    if not device:
        logger.warning('No matching UPnP devices found.')
        return 1
    
    if args.watch: show_info(device, args.watch)
        
    songs = []
    if args.list_file:
        songs = get_songs_from_m3u(args.list_file)

    if args.media_files:
        if songs:
            songs.extend(filter_aviable_songs(args.media_files))
        else:
            songs = filter_aviable_songs(args.media_files)

    # 以下逻辑都要求songs不为空
    if not songs:
        raise ValueError("songs list are empty, or all file path not aviable.")
    
    if args.shuffle_songs:
        import random
        random.shuffle(songs)
        logger.info('Shuffled the song list for random playback.')
    
    max_songs = args.max_songs or 20
    if len(songs) > max_songs:
        songs = songs[:max_songs]  # 只取前max_songs首歌，避免播放时间过长

    if args.volume_start >= 0 and args.volume_start < args.volume:
        set_volume(device, args.volume_start) # 先调低音量，以实现渐变淡入。
    else:
        set_volume(device, args.volume or 30)

    try:
        play_songs(device, songs, args.localhost, args.serve_port, args.volume or 30)
    finally:
        # 确保播放结束后删除PID文件
        remove_pid_file(pid_file_path(device.friendly_name))

    logger.info('Playback finished. Exiting.')

    return 0


if __name__ == '__main__':
    sys.exit(main())