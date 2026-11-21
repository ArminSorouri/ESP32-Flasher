$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$arduino = Join-Path $env:LOCALAPPDATA 'Arduino15'
$tools = Join-Path $root 'release_tools'
$out = Join-Path $root 'dist'

python -m pip install -r (Join-Path $root 'requirements.txt')
python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name ESP32-Flasher (Join-Path $root 'esp32_flasher.py')

$toolOut = Join-Path $out 'ESP32-Flasher\tools'
New-Item -ItemType Directory -Force $toolOut | Out-Null

# USB flashing tool and boot_app0 are copied from the locally installed
# Arduino ESP32 package. The release can then run without Arduino IDE.
$esptool = Get-ChildItem (Join-Path $arduino 'packages\esp32\tools') -Recurse -Filter esptool.exe |
  Sort-Object FullName | Select-Object -Last 1
$boot = Get-ChildItem (Join-Path $arduino 'packages') -Recurse -Filter boot_app0.bin |
  Sort-Object FullName | Select-Object -Last 1
$mdns = Get-ChildItem (Join-Path $arduino 'packages\builtin\tools') -Recurse -Filter mdns-discovery.exe |
  Sort-Object FullName | Select-Object -Last 1
$espota = Get-ChildItem (Join-Path $arduino 'packages\esp32\hardware') -Recurse -Filter espota.py |
  Sort-Object FullName | Select-Object -Last 1

Copy-Item $esptool.FullName (Join-Path $toolOut 'esptool.exe') -Force
Copy-Item $boot.FullName (Join-Path $toolOut 'boot_app0.bin') -Force
Copy-Item $mdns.FullName (Join-Path $toolOut 'mdns-discovery.exe') -Force

# Build espota as a standalone executable so end users do not need Python.
python -m PyInstaller --noconfirm --clean --onefile --console `
  --name espota $espota.FullName
Copy-Item (Join-Path $root 'dist\espota.exe') (Join-Path $toolOut 'espota.exe') -Force

Copy-Item (Join-Path $root 'README.md') (Join-Path $out 'ESP32-Flasher\README.md') -Force
Write-Host "Release prepared at $($out)\ESP32-Flasher"
