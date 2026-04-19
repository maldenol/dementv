# dementv
Make your smart TV dumb again (C).

### Why
1. You might have dementia.
2. Other people might have dementia.
3. Dementia makes life hard.

### Why not
1. You don't know what a TV is anymore.

### How
Uses the cheapest RPi to show videos from YouTube with simplest possible controls:
1. next "channel";
2. previous "channel";
3. volume up;
4. volume down;
5. on/off.

Does not show ads.  
Can play 1080p@60fps videos by Wi-Fi.  
Uses TV's own IR remote (if you can isolate TV's own IR RX).  
Controls the TV using HDMI CEC.  
Does not consume much.

### How to
1. Get any RPi. I made it for Raspberry Pi Zero W, the weakest one.
2. Connect IR RX to GPIO 27. Make sure to not exceed 8 mA (use 500 Ohm resistor).
3. Install Raspberry Pi OS Lite (32-bit trixie in my case).
4. Connect to TV by HDMI.
5. Connect to power source.
6. Create user "user".
7. Add next line to the end of `/boot/firmware/config.txt`:
```
dtoverlay=gpio-ir,gpio_pin=27
```
8. Install dependencies.
```
apt-get install python3-pip python3-websockets python3-evdev
python3 -m pip install yt-dlp --break-system-packages
```
9. Install ZeroPlay with WebSocket support ([stable and checked fork](https://github.com/maldenol/zeroplay), [latest](https://github.com/HorseyofCoursey/zeroplay)).
10. Reboot.
11. Modify dementv.py for yout needs: IR protocol, signals and YouTube search prompts. Use this line to check whether your IR RX work and which signals does your remote send:
```
sudo ir-keytable -p all -s rc0 & evtest
```
12. Copy dementv.py to ```/home/user/```.
13. Copy dementv.service and zeroplay.service to ```/etc/systemd/system/```.
14. Enable these two services.
15. Reboot. Enjoy?

### To improve
Does not currently support playing YouTube live streams at a reasonable quality.

### License
Dementia-friendly The Unlicense.
