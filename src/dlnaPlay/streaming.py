# encoding: UTF-8

import sys
import socket
import threading
from pathlib import Path

from twisted.internet import reactor
from twisted.web.resource import Resource, IResource
from twisted.web.server import Site
from twisted.web.static import File
from typing import cast

from dlnaPlay import _logger
logger = _logger.get_logger(__name__)

# 用函数自动寻找可用端口
def find_free_port(host=''):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        _, port = s.getsockname()
        return port


def get_serve_ip(target_ip, target_port=80):
    logger.debug("Identifying server IP")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((target_ip, target_port))
        serve_ip = s.getsockname()[0]
    logger.debug("Server IP identified: %s", serve_ip)
    return serve_ip

def start_server(files:list, serve_ip, serve_port=9000):

    logger.debug("Starting to create streaming server")

    root = Resource()
    file_key = "media_list"
    root.putChild(file_key.encode("utf-8"), cast(IResource, Resource()))
    mediaNode = root.children[file_key.encode("utf-8")]
    urls = {}
    sub_urls = {}

    base_url = f"http://{serve_ip}:{serve_port}/{file_key}/"
    logger.info(f"Streaming server URL Pattern: {base_url}media_x")

    for idx, file_path in enumerate(files):
        file_path = Path(file_path)
        # 保留原始文件扩展名, 以确保DLNA设备能够正确识别媒体类型。
        # 逻辑见dlna.py中的 play() 函数。

        file_name = f"media_{idx+1}{file_path.suffix}"
        mediaNode.putChild(
            file_name.encode("utf-8"), File(file_path.absolute().as_posix()))
        url = base_url + file_name
        urls[file_path.name] = url
        logger.debug(f"Added file to server: {file_path} -> {url}")

        #字幕文件支持（目前只发送一个字幕文件，且必须与视频文件同名、仅不同后缀）
        for sub_suffix in ['.srt', '.ass']:
            sub_file = file_path.with_suffix(sub_suffix)
            if sub_file.exists():
                sub_name = f"media_{idx+1}{sub_suffix}"
                mediaNode.putChild(
                    sub_name.encode("utf-8"), File(sub_file.absolute().as_posix()))
                logger.debug(f"Added subtitle file to server: {sub_file}")
                sub_urls[file_path.name] = base_url + sub_name


    logger.debug("Starting to listen messages in HTTP server")
    reactor.listenTCP(serve_port, Site(root)) # type: ignore
    server_thread = threading.Thread(
        target=reactor.run, kwargs={"installSignalHandlers": False}) # type: ignore
    server_thread.start()

    return urls, sub_urls, server_thread

def stop_server():
    logger.debug(f"Stopping the streaming server: reactor_status={reactor.running}") #type:ignore
    # 停止独立线程中的reactor服务器
    reactor.callFromThread(reactor.stop)  # type: ignore

if __name__ == '__main__':
    if len(sys.argv) >= 4:
        start_server(sys.argv[3:], sys.argv[1], len(sys.argv[2]))
    else:
        logger.warning('''usage: streaming.py <server_ip> <server_port> <file_paths>\n
                       For Example: 
                       streaming.py  192.168.1.12  19001  /media/mv/Superman.mp3 ../abc.ogg
                    
                       ''')
