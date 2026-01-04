# encoding: UTF-8

# 参考 `goblin/nanodlna` 的 devices.py

import socket
import struct
from queue import Queue
from dlnaPlay import logger

SSDP_BROADCAST_PORT = 1900
SSDP_BROADCAST_ADDR = "239.255.255.250"

SSDP_BROADCAST_PARAMS = [
    "M-SEARCH * HTTP/1.1",
    "HOST: {0}:{1}".format(SSDP_BROADCAST_ADDR, SSDP_BROADCAST_PORT),
    "MAN: \"ssdp:discover\"", "MX: 10", "ST: ssdp:all", "", ""]
SSDP_BROADCAST_MSG = "\r\n".join(SSDP_BROADCAST_PARAMS)

UPNP_DEVICE_TYPE = "urn:schemas-upnp-org:device:MediaRenderer:1"
UPNP_SERVICE_TYPE = "urn:schemas-upnp-org:service:AVTransport:1"


def scan_devices(queue:Queue, timeout=3.0, host=None):

    if not host:
        host = "0.0.0.0"
    if not timeout:
        timeout = 30
    logger.debug("Searching for devices on {}".format(host))

    logger.debug("Configuring broadcast message")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    # OpenBSD needs the ttl for the IP_MULTICAST_TTL as an unsigned char
    ttl = struct.pack("B", 4)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    s.bind((host, 0))

    logger.debug("Sending broadcast message")
    s.sendto(SSDP_BROADCAST_MSG.encode("UTF-8"), (SSDP_BROADCAST_ADDR,
                                                  SSDP_BROADCAST_PORT))

    logger.debug("Waiting for devices ({} seconds)".format(timeout))
    s.settimeout(timeout)

    # devices = []
    while True:

        try:
            data, addr = s.recvfrom(1024)
        except socket.timeout:
            break

        try:
            info = [a.split(":", 1)
                    for a in data.decode("UTF-8").split("\r\n")[1:]]
            device = dict([(a[0].strip().lower(), a[1].strip())
                           for a in info if len(a) >= 2])
            logger.debug("Device broadcast response: %s \n" \
                            "    data:\n    %s\n" \
                            "    in_json:\n    %s",
                          data, device)

            # 筛选DLNA播放设备            
            if device.get('st') and "AVTransport" in device["st"]:
                # devices.append(device)
                queue.put(device.get("location"))
           
        except Exception:
            pass
    
    queue.put("TIMEOUT")

    return 
