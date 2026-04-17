import asyncio
import datetime
import evdev
import json
import os
import random
import subprocess
import sys
import threading
import time
import websockets


BEST_RESOLUTION = "720"
SEARCH_PROMPTS = {
    "новини" : 20,
    "днк свої" : 15,
    "советские фильмы" : 10,
}
VIDEO_UPDATE_COOLDOWN = 5.0 * 60.0 * 60.0 # YT streams expire after 6 hours

PLAY_COOLDOWN = 5.0
EOS_COOLDOWN = 10.0

IR_PROTOCOL = "nec"
IR_RX_COMMANDS = {
    "PWR"      : ("0x7f0a", "0x7f0b", ),
    "CH_NEXT"  : ("0x7ffb", ),
    "CH_PREV"  : ("0x7ffa", ),
    "VOL_UP"   : ("0x7ff9", ),
    "VOL_DOWN" : ("0x7ff8", ),
}
IR_TX_COMMANDS = {
    "PWR"      : "0x7f0a",
    "VOL_UP"   : "0x7ff9",
    "VOL_DOWN" : "0x7ff8",
}
IR_COMMAND_COOLDOWN = 1.0


videos = []
current_video_index = None
is_playing = False
websocket_server_loop = None
websocket_client = None


def log(message):
    print(datetime.datetime.now().isoformat(), ": ", message, file=sys.stderr)


def search_video_ids(prompt, num):
    cmd = [
        "yt-dlp",
        "-q",
        "--no-warnings",
        "--get-id",
        f"ytsearch{num}:{prompt}"
    ]
    out = subprocess.check_output(cmd, text=True)
    ids = out.strip().splitlines()
    return ids

def get_video_urls(id):
    cmd = [
        "yt-dlp",
        "-q",
        "--no-warnings",
        "--get-url",
        "-f",
        f"bv[ext=mp4][vcodec^=avc][height<={BEST_RESOLUTION}]+ba[ext=m4a]",
        f"https://youtube.com/watch?v={id}"
    ]
    try:
        out = subprocess.check_output(cmd, text=True)
        urls = out.strip().splitlines()
        video_url = urls[0] if len(urls) > 0 else None
        audio_url = urls[1] if len(urls) > 1 else None
        return (video_url, audio_url)
    except subprocess.CalledProcessError:
        return (None, None)

def prepare_video_list():
    log(f"Status: Preparing new video list")

    videos = []
    for prompt, num in SEARCH_PROMPTS.items():
        log(f"Status: Searching {num} videos for \"{prompt}\"...")
        videos += [{"id" : id} for id in search_video_ids(prompt, num)]
    random.shuffle(videos)

    log(f"Status: Found {len(videos)} video IDs")
    log(f"Status: Getting video and audio HLS streams' URLs")

    for video in videos:
        (video_url, audio_url) = get_video_urls(video["id"])
        video["video"] = video_url
        video["audio"] = audio_url
    videos[:] = [video for video in videos if not video["audio"] is None]

    log(f"Status: New list of {len(videos)} videos is ready")

    return videos

def update_video_list_thread_function():
    global videos, current_video_index

    last_update_time = 0.0
    while True:
        current_time = time.time()
        sleep_time = last_update_time + VIDEO_UPDATE_COOLDOWN - current_time
        if sleep_time <= 0.0:
            last_update_time = current_time

            new_videos = prepare_video_list()
            videos = new_videos
            current_video_index = -1
        else:
            time.sleep(sleep_time)


def play_video(video):
    global websocket_server_loop, websocket_client

    if not websocket_client or not websocket_server_loop:
        log("ERROR: No websocket client connected")
        return

    log(f"Status: Playing: {video["id"]}")
    message = json.dumps({
        "op": "load",
        "url": f"({video["video"]})({video["audio"]})",
    })
    asyncio.run_coroutine_threadsafe(websocket_client.send(message), websocket_server_loop)


async def websocket_client_handler(client):
    global is_playing, websocket_client
    log("Status: Websocket client connected")
    websocket_client = client
    try:
        async for message in client:
            message = json.loads(message)
            if "idle" in message:
                is_playing = not message["idle"]
    finally:
        websocket_client = None
        log("ERROR: Websocket client disconnected")

async def websocket_server():
    async with websockets.serve(websocket_client_handler, "127.0.0.1", 8888):
        await asyncio.Future()

def websocket_server_thread_function():
    global websocket_server_loop
    websocket_server_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(websocket_server_loop)
    websocket_server_loop.run_until_complete(websocket_server())


def ir_rx_init():
    for device in [evdev.InputDevice(path) for path in evdev.list_devices()]:
        if "gpio_ir_recv" in device.name:
            return device
    return None

def ir_tx_init():
    for index in range(0, 2):
        if os.system(f"ir-ctl -d /dev/lirc{index} -S {IR_PROTOCOL}:0x0000") == 0:
            return index
    return None

def ir_rx(ir_rx_device):
    event = ir_rx_device.read_one()
    if not event is None:
        return str(hex(event.value))
    return None

def ir_tx(ir_tx_index, cmd):
    os.system(f"ir-ctl -d /dev/lirc{ir_tx_index} -S {IR_PROTOCOL}:{cmd}")


def main():
    ir_rx_device = ir_rx_init()
    if ir_rx_device is None:
        log("ERROR: IR RX not found")
        exit(-1)
    ir_tx_index = ir_tx_init()
    if ir_tx_index is None:
        log("ERROR: IR TX not found")
        exit(-1)
    if not os.system(f"ir-keytable -p {IR_PROTOCOL} -s rc{1 - ir_tx_index}") == 0:
        exit(-1)
    log("Status: IR ready")

    threading.Thread(target=websocket_server_thread_function, daemon=True).start()
    log("Status: Websocket server ready")

    threading.Thread(target=update_video_list_thread_function, daemon=True).start()

    global videos, current_video_index, is_playing

    last_cmd_time = 0
    while True:
        event = ir_rx(ir_rx_device)
        if not event is None:
            if time.time() - last_cmd_time > IR_COMMAND_COOLDOWN:
                last_cmd_time = time.time()
            else:
                continue

            if event in IR_RX_COMMANDS["PWR"]:
                log("Event: PWR")
                ir_tx(ir_tx_index, IR_TX_COMMANDS["PWR"])
            elif event in IR_RX_COMMANDS["CH_NEXT"]:
                log("Event: CH_NEXT")
                if len(videos) > 0:
                    current_video_index += 1
                    current_video_index %= len(videos)
                    play_video(videos[current_video_index])
                    time.sleep(PLAY_COOLDOWN)
            elif event in IR_RX_COMMANDS["CH_PREV"]:
                log("Event: CH_PREV")
                if len(videos) > 0:
                    current_video_index -= 1
                    current_video_index %= len(videos)
                    play_video(videos[current_video_index])
                    time.sleep(PLAY_COOLDOWN)
            elif event in IR_RX_COMMANDS["VOL_UP"]:
                log("Event: VOL_UP")
                ir_tx(ir_tx_index, IR_TX_COMMANDS["VOL_UP"])
            elif event in IR_RX_COMMANDS["VOL_DOWN"]:
                log("Event: VOL_DOWN")
                ir_tx(ir_tx_index, IR_TX_COMMANDS["VOL_DOWN"])

        if not is_playing:
            time.sleep(EOS_COOLDOWN)
            if not is_playing:
                log("Event: EOS")
                if len(videos) > 0:
                    current_video_index += 1
                    current_video_index %= len(videos)
                    play_video(videos[current_video_index])

        time.sleep(0.1)


if __name__ == "__main__":
    main()
