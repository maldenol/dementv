import asyncio
import datetime
import evdev
import json
import math
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
FIRST_VIDEO_UPDATE_NUMBER_REDUCTION = 10.0

PLAY_COOLDOWN = 10.0

IR_PROTOCOL = "nec"
IR_RX_COMMANDS = {
    "PWR"      : (69, 70, 71, ),
    "CH_NEXT"  : ( 7, 21,  9, ),
    "CH_PREV"  : (22, 25, 13, ),
    "VOL_UP"   : ( 8, 28, 90, ),
    "VOL_DOWN" : (66, 82, 74, ),
}
IR_RX_COOLDOWN = 2.0

HDMI_CEC_COMMANDS = {
    "PWR_ON"   : "power-on-function",
    "PWR_OFF"  : "power-off-function",
    "VOL_UP"   : "volume-up",
    "VOL_DOWN" : "volume-down",
}


videos = []
current_video_index = -1
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

def prepare_video_list(first = False):
    log(f"Status: Preparing new video list")

    videos = []
    for prompt, num in SEARCH_PROMPTS.items():
        if first:
            num = math.ceil(num / FIRST_VIDEO_UPDATE_NUMBER_REDUCTION)

        log(f"Status: Searching {num} videos for \"{prompt}\"...")
        videos += [{"id" : id} for id in search_video_ids(prompt, num)]
    random.shuffle(videos)

    log(f"Status: Found {len(videos)} video IDs")
    log(f"Status: Getting video and audio HLS streams' URLs")

    for video in videos:
        (video_url, audio_url) = get_video_urls(video["id"])
        video["video"] = video_url
        video["audio"] = audio_url
        log(f"Status: Found video {video["id"]}")
    videos[:] = [video for video in videos if not video["audio"] is None]

    log(f"Status: New list of {len(videos)} videos is ready")

    return videos

def update_video_list_thread_function():
    global videos, current_video_index

    videos = prepare_video_list(True)

    last_update_time = 0.0
    while True:
        current_time = time.time()
        sleep_time = last_update_time + VIDEO_UPDATE_COOLDOWN - current_time
        if sleep_time <= 0.0:
            last_update_time = current_time

            new_videos = prepare_video_list()
            videos = new_videos
        else:
            time.sleep(sleep_time)


def websocket_client_send(message):
    global websocket_server_loop, websocket_client

    if not websocket_client or not websocket_server_loop:
        log("ERROR: No websocket client connected")
        return

    asyncio.run_coroutine_threadsafe(websocket_client.send(message), websocket_server_loop)

def set_is_playing(new_is_playing):
    global is_playing
    was_playing = is_playing
    is_playing = new_is_playing
    if not is_playing == was_playing:
        log(f"Status: Playing = {is_playing}")

def stop_video():
    global websocket_client

    log(f"Status: Killing ZeroPlay")
    os.system("killall -s 9 zeroplay")

    websocket_client = None

    set_is_playing(False)

    while websocket_client is None:
        time.sleep(0.1)

def play_video(video):
    global is_playing

    stop_video()

    log(f"Status: Playing: {video["id"]}")
    message = json.dumps({
        "op": "load",
        "url": f"({video["video"]})({video["audio"]})",
    })
    websocket_client_send(message)

    sleep_time_left = PLAY_COOLDOWN
    while (not is_playing) and (sleep_time_left > 0.0):
        delta = 0.1
        sleep_time_left -= delta
        time.sleep(delta)
    if not is_playing:
        log(f"ERROR: Can't play current video")
        stop_video()


async def websocket_client_handler(client):
    global is_playing, websocket_client
    log("Status: Websocket client connected")
    websocket_client = client
    try:
        async for message in client:
            message = json.loads(message)
            if "idle" in message:
                set_is_playing(not message["idle"])
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


def hdmi_cec_tx_init():
    return os.system("cec-ctl --tv") == 0

def hdmi_cec_tx(command):
    os.system(f"cec-ctl --to TV --user-control-pressed=ui-cmd={command}")


def ir_rx_init():
    return os.system(f"ir-keytable -p {IR_PROTOCOL} -s rc0") == 0

def ir_rx_find():
    for device in [evdev.InputDevice(path) for path in evdev.list_devices()]:
        if "gpio_ir_recv" in device.name:
            return device
    return None

def ir_rx(ir_rx_device):
    event = ir_rx_device.read_one()
    while not ir_rx_device.read_one() is None:
        pass
    return event.value if not event is None else None


def main():
    if not hdmi_cec_tx_init():
        log("ERROR: HDMI CEC device not found")
        exit(-1)
    log("Status: HDMI CEC ready")

    if not ir_rx_init():
        log("ERROR: IR RX device not found")
        exit(-1)
    ir_rx_device = ir_rx_find()
    log("Status: IR ready")

    threading.Thread(target=websocket_server_thread_function, daemon=True).start()
    log("Status: Websocket server ready")

    threading.Thread(target=update_video_list_thread_function, daemon=True).start()

    global videos, current_video_index, is_playing

    pwr_on = True

    while True:
        event = ir_rx(ir_rx_device)
        if not event is None:
            if event in IR_RX_COMMANDS["PWR"]:
                log("Event: PWR")
                pwr_on = not pwr_on
                for _ in range(5):
                    hdmi_cec_tx(HDMI_CEC_COMMANDS["PWR_ON" if pwr_on else "PWR_OFF"])
                    time.sleep(1.0)
                if not pwr_on:
                    stop_video()
            elif event in IR_RX_COMMANDS["CH_NEXT"]:
                log("Event: CH_NEXT")
                if len(videos) > 0:
                    current_video_index += 1
                    current_video_index %= len(videos)
                    play_video(videos[current_video_index])
            elif event in IR_RX_COMMANDS["CH_PREV"]:
                log("Event: CH_PREV")
                if len(videos) > 0:
                    current_video_index -= 1
                    current_video_index %= len(videos)
                    play_video(videos[current_video_index])
            elif event in IR_RX_COMMANDS["VOL_UP"]:
                log("Event: VOL_UP")
                hdmi_cec_tx(HDMI_CEC_COMMANDS["VOL_UP"])
            elif event in IR_RX_COMMANDS["VOL_DOWN"]:
                log("Event: VOL_DOWN")
                hdmi_cec_tx(HDMI_CEC_COMMANDS["VOL_DOWN"])

        if pwr_on and not is_playing:
            if len(videos) > 0:
                log("Event: EOS")
                current_video_index += 1
                current_video_index %= len(videos)
                play_video(videos[current_video_index])

        ir_rx(ir_rx_device)

        time.sleep(IR_RX_COOLDOWN)


if __name__ == "__main__":
    main()
