# DLNAPlay

[简体中文](./README.md) | English

## Descibe

Scans for DLNA devices on the local network, matches them by name, and streams local music or videos to the device for playback.
Github source code address: [sffzh/dlnaPlay](https://github.com/sffzh/dlnaPlay)

### Features:

1. You can play media files from a list(such as playlist m3u file content), or specify multiple files to play sequentially or randomly;
2. Saves a temporary file after scanning local network devices, allowing for quick streaming skipping scanning works the next time;
3. Uses an asynchronous scanning mechanism for local network devices; streaming starts immediately upon discovering the specified device, without waiting for the scan to time out.

### Dependencies 

The functions in this program that control UPnP devices (viewing device information and Actions, playback, pause, volume adjustment, etc.) depend on the project [flyte/upnpclient](https://github.com/flyte/upnpclient). 

(Since version 1.0.6 I copied some code from flyte/upnpclient and rewrite it, removed unwanted functions, and discarded dependcies such as lxml )



## Install

```sh
pip install dlnaPlay
```

## Usage

Use `dlnaPlay -h` to show all parameter options

```sh
dlnaPlay -h
```

## Usage Examples

### List available devices

```sh
dlnaPlay -w list_devices
```
The `-w` parameter means `watch`, used to view device status without performing control operations. More details will be provided later. ` -w list_devices` will list DLNA-enabled devices after scanning the local network for UPnP devices. The program will terminate after the defined timeout period.
The timeout period in seconds can be set using the `-t` parameter, the default is 5 seconds.

Note that the results of network scanning are uncertain. If no devices are found during the scan, you can increase the timeout period and try again.
Typically, devices on a home local area network can be scanned within 5 seconds. If no devices are found after 20 seconds, you need to check the device's own network issues.
Increasing the scan time to more than 30 seconds is usually pointless.


### Playing an m3u playlist to a specified device

Suppose I have a DLNA-enabled speaker on my local network, with the UPnP name `SUPER Sound X9-9527`.

```sh
dlnaPlay -d "X9-9527" -f ~/music/playlist/favorite.m3u -s -v 30 -M 15
```

> Explanation:
> `-d` Specifies the device name; only a small portion of the full name is needed. The first device found that matches the name will be used. 
The device name is the value of the "friendly_name" field in its UPnP description file.
> `-f` Specifies the m3u playlist file. The file content is plain text, with each line corresponding to a song file. Relative or absolute paths can be used. Relative paths are relative to the m3u file. Media files support common formats such as `mp3`, `flac`, `ogg`, `m4a`, `mp4`, etc., both video and audio are supported. Video casting requires device support.
> `-s` Lowercase `s`, indicates `shuffle` random playback, which will randomly sort the songs before playing.
> `-v` Lowercase, sets the playback volume.
> `-M` Uppercase, sets the number of songs to play. Note that if `-s` random playback is set, the order will be shuffled first before selecting the number of tracks, so you don't have to worry about songs at the end of the playlist not being randomly played.

You can choose a small portion of the device name, but you need to ensure that it doesn't match multiple different devices. If multiple devices match, the first device scanned will be automatically selected.

### Specifying Media Files for Playback

The `-m` parameter can be used to directly specify media files. This parameter can be used multiple times to select multiple files. Invalid file paths will be automatically skipped.

```sh
dlnaPlay -d "-TV" -m "../videos/Love Harder(part 1).mp4" -m "../videos/Love Harder(part 2).mp4" -v 30
```

### Stream a url to a device

```sh
dlnaPlay  -d living_room_tv -v 30 -u https://lhttp-hw.qtfm.cn/live/1270/64k.mp3?app_id=web -ws 150 -st 7200 
```

> use `-u <url>` to specify an existed url for playback. It could be a web radio or web videos.
> use `-ws <seconds>` or `--wait_start <seconds>` to force program to wait more seconds before ready to play, or other wise it may exit automaticly when the url connecting too long.
> `-st <seconds>` option let program to exit after certain seconds. It can be nesessary if  you stream a web audio url, since you might forget to turn off your deivce.


### Stopping Playback

For playback tasks executed from the command line, using `Ctrl+C` or killing the process will send a signal to the DLNA playback device to stop playback before the command exits.

However, if you use `kill -9` to forcibly terminate the task, the program will be forcibly interrupted, and the DLNA device will not receive the stop playback signal and will continue playing until all cached data has been played. (This usually takes a few seconds; devices with larger caches may play an entire song.)

If you use this program to play multiple songs and directly stop playback on the DLNA device midway, the program will automatically start playing the next song after a short delay. This is because the program polls the device status to determine when a song has finished playing and it's time to play the next one.

If the command line is running in the background and you want to stop playback, there are two methods:

* 1. Directly use `ps` to view the process and then kill the process.
* 2. Use the program to specify the device name to stop playback. The command is similar to:

### Set a `sleep time` to stop playing

use `-st <seconds>` (or `--sleep_time  <seconds>`) to set up a time counter, which would stop media palying and exit the program when time out.

```sh
dlnaPlay -d X9-9527 -S
```
> `-d X9-9527` specifies the device to stop playback on, and `-S` is a capital letter, meaning `Stop`, to stop playback.


## Extra

### About M3U palylist file

a example m3u file could be like below:

```m3u
#EXTM3U
../songs/Michael Jackson - Beat It (Single Version).mp3
../songs/Carly Rae Jepsen - I Really Like You.mp3
../MV/Taylor Swift - Look What You Made Me Do.mp4
../flac/Billie Eilish - you should see me in a crown.flac

```
Each line refers to a media file using a relative path.

