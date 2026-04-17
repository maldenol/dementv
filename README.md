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
5. on/off;

and without ads. Is controlled by TV's own IR remote (IR man-in-the-middle). Can play 1080p@60fps videos by Wi-Fi.
Connects to TV by HDMI. Consumes a little. YouTube video search prompts you can specify.

### How to
1. Get any RPi. I made it for Raspberry Pi Zero W, the weakest one.
2. Connect IR RX to GPIO 27 and IR TX to GPIO 12.
3. Install Raspberry Pi OS Lite (32-bit trixie in my case).
4. Connect to TV by HDMI.
5. Connect to power source.
6. Create user "user".
7. Add next lines to the end of `/boot/firmware/config.txt`:
```
dtoverlay=gpio-ir,gpio_pin=27
dtoverlay=pwm-ir-tx,gpio_pin=12,func=4
```
8. Install dependencies.
```
apt-get install python3-pip python3-websockets python3-evdev
python3 -m pip install yt-dlp --break-system-packages
```
9. Install ZeroPlay with websocket support ([stable](https://github.com/maldenol/zeroplay), [latest](https://github.com/HorseyofCoursey/zeroplay)).
10. Reboot.
11. Modify dementv.py for yout needs: IR protocol, signals and YouTube search prompts. Use these lines to check whether your IR RX and TX work and which signals does your remote send:
```
sudo ir-keytable -p all -s rc<0_or_1> & evtest # check RX
ir-ctl -d /dev/lirc<0_or_1> -S <ir_protocol>:0x0000 # check TX
```
12. Copy dementv.py to ```/home/user/```.
13. Copy dementv.service and zeroplay.service to ```/etc/systemd/system/```.
14. Enable these two services.
15. Reboot. Enjoy?

### Difference
If your TV is controlled by Bluetooth, you might need to replace IR with BT support.
If your TV has HDMI CEC (best scenario), you might use it to control the TV instead of IR.
If your TV has ADB activated, you might use it to control the TV instead of IR.

### To improve
Does not currently support playing YouTube live streams at a reasonable quality.

### License
Dementia-friendly The Unlicense.
