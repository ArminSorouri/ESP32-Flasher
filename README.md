# ESP32 Flasher for Windows

A Windows application for flashing pre-built ESP32 firmware over USB or OTA. Portable releases do not require Python, Arduino IDE, or command-line tools.

## For users

Download the latest ZIP from **GitHub Releases**, extract it, and run `ESP32-Flasher.exe`.

### USB flash

1. Connect the ESP32 with a data USB cable.
2. Select the COM port.
3. Select the folder containing the build images.
4. Click **FLASH (no compile)**.
5. If it stops at `Connecting...`, hold BOOT, press and release EN, then release BOOT when writing starts.

### OTA upload

The ESP32 must already run firmware with ArduinoOTA enabled and be on the same LAN.

1. Click **SEARCH** in the OTA section.
2. Select an entry such as `monitoring-26111034 at 192.168.1.134`.
3. Enter the OTA password.
4. Select the application image ending in `.ino.bin`.
5. Click **UPLOAD OTA**.

OTA uses only the application image. Bootloader, partition, and `boot_app0` files are not used for OTA.

## Building from source

Install Python 3.10+ and run:

```powershell
python -m pip install -r requirements.txt
python esp32_flasher.py
```

To build the portable release, run PowerShell on a machine with the Arduino ESP32 package installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

The output is created under `dist\ESP32-Flasher`. The build script copies `esptool`, `espota`, `mdns-discovery`, and `boot_app0` into the portable package.

## Network and firewall

The computer and ESP32 must be on the same local network. Discovery uses Arduino network-port discovery and OTA uses TCP port `3232`. The OTA transfer also needs host return port `3233`; Windows Firewall may show a permission prompt on first use.

If discovery is blocked, enter the ESP IP address manually. Upload does not require a USB connection.

## Security

Do not commit OTA passwords or firmware secrets. Keep deployment passwords outside the repository and review firewall rules before using the tool on an untrusted network.

## License

MIT. See [LICENSE](LICENSE).
