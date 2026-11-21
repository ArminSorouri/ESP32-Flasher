# ESP32 Flasher for Windows

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![Target](https://img.shields.io/badge/target-ESP32%20classic-E7352C)
![License](https://img.shields.io/badge/license-MIT-green)

A portable Windows utility for flashing pre-built firmware to classic ESP32 boards over USB or OTA. It is intended for technicians and end users who should not need Python, Arduino IDE, or command-line tools.

The current release targets classic Xtensa ESP32 boards, including ESP32-WROOM-32, WROOM-32U, WROOM-32UE, and compatible DevKit boards.

## Features

- USB flashing of bootloader, partition table, `boot_app0`, and application images.
- OTA upload using the application `.ino.bin` image.
- Arduino-compatible network discovery.
- Displays the OTA hostname and IP, for example `monitoring-26111034 at 192.168.1.134`.
- Automatic detection of COM ports and compiled binary files.
- Integrated USB serial monitor.
- Automatic selection of the local IP and a fixed OTA return port.
- Password-protected OTA upload support.
- Portable release that does not require Python or Arduino IDE.

## Supported hardware

The USB flasher currently uses the classic ESP32 target and is tested with:

- ESP32-WROOM-32
- ESP32-WROOM-32U
- ESP32-WROOM-32UE
- ESP32 DevKit boards based on the classic ESP32

ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6, and ESP32-H2 are not currently supported by the USB flashing profile. OTA support depends on the firmware being built for the target chip and enabling `ArduinoOTA`.

## Download for normal users

1. Open the **Releases** page.
2. Download the latest portable ZIP.
3. Extract it to a local folder.
4. Run `ESP32-Flasher.exe`.

No installation is required. Windows Defender or SmartScreen may show a warning for unsigned community software; verify the release source before allowing it.

## USB flashing

USB flashing requires a compiled firmware folder containing:

```text
*.bootloader.bin
*.partitions.bin
boot_app0.bin
*.ino.bin
```

1. Connect the ESP32 with a data-capable USB cable.
2. Select the COM port.
3. Click **Browse** and select the build folder.
4. Confirm the detected files.
5. Click **FLASH (no compile)**.
6. If the tool remains at `Connecting...`, hold **BOOT**, press and release **EN**, and release BOOT when writing begins.

The default USB profile is intended for 4 MB classic ESP32 boards with the standard Arduino partition layout.

## OTA upload

The ESP32 must already be running firmware with `ArduinoOTA` enabled and must be connected to the same LAN as the computer.

1. Click **SEARCH** in the OTA section.
2. Select the discovered entry, such as:

   ```text
   monitoring-26111034 at 192.168.1.134
   ```

3. Enter the OTA password.
4. Select the application image ending in `.ino.bin`.
5. Click **UPLOAD OTA**.

Only the application image is used for OTA. Do not select the bootloader, partition table, `boot_app0`, or merged image for OTA.

The ESP32 Arduino OTA protocol uses TCP port `3232`. The upload tool uses host return port `3233`; Windows Firewall must allow that port on a trusted Private network.

## Building from source

For development, install Python 3.10 or newer:

```powershell
python -m pip install -r requirements.txt
python esp32_flasher.py
```

The source build can use tools from a local Arduino ESP32 installation. To create a portable release, run PowerShell on a build machine with the Arduino ESP32 package installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

The resulting package is created under:

```text
dist\ESP32-Flasher\
```

The build script bundles the required `esptool`, `espota`, `mdns-discovery`, and `boot_app0` files into the release package.

## Network discovery troubleshooting

- Keep the computer and ESP32 on the same LAN and IP subnet.
- Set the Windows network profile to **Private**.
- Allow `mdns-discovery.exe` through Windows Firewall on Private networks.
- Allow TCP port `3233` for the OTA return connection.
- If discovery is unavailable, enter the ESP IP address manually.
- Arduino IDE can be used as a comparison tool: if it shows a Network Port, the ESP is advertising OTA correctly.

## Security

- Do not commit OTA passwords, firmware keys, certificates, or `secrets.h`.
- Use a unique OTA password per deployment where possible.
- Use the tool only on trusted networks.
- Review Windows Firewall rules before using the tool on a public network.
- This tool uploads firmware; it does not compile or cryptographically sign firmware images.

## Repository layout

```text
ESP32-Flasher/
├── esp32_flasher.py
├── build_release.ps1
├── flash_esp32.bat
├── requirements.txt
├── VERSION
├── LICENSE
└── README.md
```

## Contributing

Bug reports and pull requests are welcome. Include the Windows version, ESP32 target, Arduino ESP32 core version, connection method (USB or OTA), and the relevant Flasher log. Never include passwords or firmware secrets in an issue or pull request.

## License

Released under the MIT License. See [LICENSE](LICENSE).
