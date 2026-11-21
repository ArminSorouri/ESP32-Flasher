# -*- coding: utf-8 -*-
"""ESP32 flasher with a small Tkinter UI.

Flashes pre-built binaries (no compile) using esptool, and includes an
integrated serial monitor. The serial monitor is automatically stopped
before flashing so it never blocks the COM port.
"""

import os
import glob
import re
import sys
import socket
import struct
import threading
import subprocess
import time
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import serial
import serial.tools.list_ports
from concurrent.futures import ThreadPoolExecutor, as_completed

APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)
LOCAL_TOOLS_DIR = os.path.join(APP_DIR, "tools")

def find_mdns_discovery():
    local = os.path.join(LOCAL_TOOLS_DIR, "mdns-discovery.exe")
    if os.path.isfile(local):
        return local
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arduino15")
    cands = []
    for dirpath, _, files in os.walk(root):
        if "mdns-discovery.exe" in files:
            cands.append(os.path.join(dirpath, "mdns-discovery.exe"))
    return sorted(cands)[-1] if cands else None

MDNS_DISCOVERY = find_mdns_discovery()

def find_arduino_cli():
    p = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Arduino IDE",
                     "resources", "app", "lib", "backend", "resources", "arduino-cli.exe")
    return p if os.path.isfile(p) else "arduino-cli"

ARDUINO_CLI = find_arduino_cli()

def find_espota():
    for name in ("espota.exe", "espota.py"):
        local = os.path.join(LOCAL_TOOLS_DIR, name)
        if os.path.isfile(local):
            return local
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arduino15")
    cands = []
    for dirpath, _, files in os.walk(root):
        if "espota.py" in files and os.path.basename(dirpath) == "tools":
            cands.append(os.path.join(dirpath, "espota.py"))
    return sorted(cands)[-1] if cands else None


def local_ipv4_subnet():
    """Return the local /24 subnet without sending application traffic."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
    finally:
        s.close()
    parts = ip.split(".")
    return ".".join(parts[:3]) if len(parts) == 4 else None


def local_ipv4_for_target(target):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 3232))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def mdns_arduino_hosts(timeout=2.0):
    """Discover ArduinoOTA services like Arduino IDE via mDNS."""
    qname = b"".join(bytes([len(part)]) + part.encode() for part in ("_arduino", "_tcp", "local")) + b"\0"
    packet = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + qname + struct.pack(">HH", 12, 1)
    found = set()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(timeout)
        s.sendto(packet, ("224.0.0.251", 5353))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                break
            if len(data) < 12:
                continue
            qd, an, ns, ar = struct.unpack_from(">HHHH", data, 4)
            off = 12

            def skip_name(pos):
                while pos < len(data):
                    n = data[pos]
                    if n == 0:
                        return pos + 1
                    if (n & 0xC0) == 0xC0:
                        return pos + 2
                    pos += n + 1
                return pos

            off = skip_name(off) + 4 * qd
            for _ in range(an + ns + ar):
                off = skip_name(off)
                if off + 10 > len(data):
                    break
                rtype, rclass, ttl, rdlen = struct.unpack_from(">HHIH", data, off)
                off += 10
                rdata = data[off:off + rdlen]
                off += rdlen
                if rtype == 1 and rdlen == 4:
                    found.add(socket.inet_ntoa(rdata))
    finally:
        s.close()
    return sorted(found, key=lambda x: tuple(int(v) for v in x.split(".")))


def arduino_tool_mdns_hosts(timeout=3.0):
    """Use Arduino's own mdns-discovery protocol, same as Arduino IDE."""
    if not MDNS_DISCOVERY:
        return []
    p = subprocess.Popen([MDNS_DISCOVERY], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    try:
        p.stdin.write('HELLO 1 "esp-flasher"\nSTART_SYNC\n')
        p.stdin.flush()
        time.sleep(timeout)
        p.kill()
        out, _ = p.communicate(timeout=3)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
        return []
    found = set()
    for line in out.splitlines():
        try:
            event = json.loads(line)
            port = event.get("port", {})
            if event.get("eventType") == "add" and port.get("protocol") == "network":
                if port.get("address"):
                    found.add(port["address"])
        except (ValueError, TypeError):
            continue
    return sorted(found, key=lambda x: tuple(int(v) for v in x.split(".")))


def arduino_tool_mdns_devices(timeout=3.0):
    if not MDNS_DISCOVERY:
        return []
    p = subprocess.Popen([MDNS_DISCOVERY], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    try:
        p.stdin.write('HELLO 1 "esp-flasher"\nSTART_SYNC\n'); p.stdin.flush()
        time.sleep(timeout)
        p.kill()
        out, _ = p.communicate(timeout=3)
    except Exception:
        try: p.kill()
        except Exception: pass
        return []
    found = []
    for line in out.splitlines():
        try:
            event = json.loads(line); port = event.get("port", {})
            if event.get("eventType") == "add" and port.get("protocol") == "network":
                address = port.get("address"); label = port.get("label", address)
                if address: found.append((label, address))
        except (ValueError, TypeError):
            continue
    return found


def arduino_cli_network_hosts():
    return [address for _, address in arduino_cli_network_devices()]


def arduino_cli_network_devices():
    """Return (Arduino IDE label, IP) pairs from board list."""
    try:
        out = subprocess.check_output([ARDUINO_CLI, "board", "list", "--json",
                                       "--discovery-timeout", "3s"],
                                      stderr=subprocess.STDOUT,
                                      text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        payload = json.loads(out)
    except ValueError:
        return []
    devices = []
    for item in payload.get("detected_ports", []):
        port = item.get("port", {})
        if port.get("protocol") != "network":
            continue
        address = port.get("address", "")
        try:
            socket.inet_aton(address)
        except OSError:
            continue
        devices.append((port.get("label", address), address))
    return devices


def scan_ota_hosts(port=3232):
    """Find ArduinoOTA devices using Arduino mDNS, then fallback scans."""
    cli_hosts = arduino_cli_network_hosts()
    if cli_hosts:
        return cli_hosts
    mdns_tool = arduino_tool_mdns_hosts()
    if mdns_tool:
        return mdns_tool
    mdns = mdns_arduino_hosts()
    if mdns:
        return mdns
    subnet = local_ipv4_subnet()
    if not subnet:
        return []

    def probe(n):
        ip = f"{subnet}.{n}"
        try:
            with socket.create_connection((ip, port), timeout=0.18):
                return ip
        except OSError:
            return None

    found = []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for f in as_completed([pool.submit(probe, n) for n in range(1, 255)]):
            ip = f.result()
            if ip:
                found.append(ip)
    return sorted(found, key=lambda x: tuple(int(v) for v in x.split(".")))

def find_esptool():
    local = os.path.join(LOCAL_TOOLS_DIR, "esptool.exe")
    if os.path.isfile(local):
        return local
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arduino15")
    cands = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f == "esptool.exe" and "esptool_py" in dirpath.replace("\\", "/"):
                cands.append(os.path.join(dirpath, f))
    if not cands:
        return None
    return sorted(cands)[-1]

ESPTOOL = find_esptool() or r"C:\Users\Armin\AppData\Local\Arduino15\packages\esp32\tools\esptool_py\5.3.0\esptool.exe"
BAUD_FLASH = 921600
BAUD_MONITOR = 115200
ESPOTA = find_espota()
OTA_HOST_PORT = 3233


def find_boot_app0():
    local = os.path.join(LOCAL_TOOLS_DIR, "boot_app0.bin")
    if os.path.isfile(local):
        return local
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arduino15")
    for dirpath, _, files in os.walk(root):
        for f in files:
            if f == "boot_app0.bin":
                return os.path.join(dirpath, f)
    return None


def esptool_cli_options():
    output = subprocess.check_output(
        [ESPTOOL, "version"], stderr=subprocess.STDOUT, universal_newlines=True)
    match = re.search(r"(?:^|\s)v?(\d+)\.\d+", output)
    if not match:
        raise RuntimeError("Could not determine the esptool version.")
    # The pictured DevKit has the usual EN/BOOT auto-reset wiring.  Let
    # esptool toggle DTR/RTS and enter download mode automatically.  The old
    # no-reset mode required a perfectly timed manual BOOT press and caused
    # "No serial data received" on this board.
    if int(match.group(1)) >= 5:
        return "write-flash", "default-reset", "hard-reset", "--flash-mode", "--flash-freq", "--flash-size"
    return "write_flash", "default_reset", "hard_reset", "--flash_mode", "--flash_freq", "--flash_size"


def detect_bins(folder):
    result = {"bootloader": None, "partitions": None, "app": None, "boot_app0": find_boot_app0()}
    if not folder or not os.path.isdir(folder):
        return result
    bins = [os.path.join(folder, f) for f in os.listdir(folder)
            if f.lower().endswith(".bin")]
    # Arduino CLI places the boot_app0 image beside the other build outputs.
    # Prefer it over a copy found elsewhere under Arduino15; this prevents
    # mixing a boot_app0 from an older ESP32 core with the current build.
    for p in bins:
        if os.path.basename(p).lower() == "boot_app0.bin":
            result["boot_app0"] = p
            break
    for p in bins:
        name = os.path.basename(p).lower()
        if "bootloader" in name and result["bootloader"] is None:
            result["bootloader"] = p
        elif "partitions" in name and result["partitions"] is None:
            result["partitions"] = p
        elif name.endswith(".ino.bin") and result["app"] is None:
            result["app"] = p
    if result["app"] is None and bins:
        candidates = [p for p in bins
                      if "bootloader" not in os.path.basename(p).lower()
                      and "partitions" not in os.path.basename(p).lower()]
        if candidates:
            result["app"] = max(candidates, key=os.path.getsize)
    return result


class FlasherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ESP32 Flasher (no compile)")
        self.geometry("780x640")
        self.minsize(720, 580)

        self.com_var = tk.StringVar()
        self.folder_var = tk.StringVar()
        self.bootloader_var = tk.StringVar()
        self.partitions_var = tk.StringVar()
        self.app_var = tk.StringVar()
        self.boot_app0_var = tk.StringVar(value=find_boot_app0() or "")
        self.ota_host_var = tk.StringVar()
        self.ota_display_var = tk.StringVar()
        self.ota_port_var = tk.StringVar(value="3232")
        self.ota_password_var = tk.StringVar()
        self.ota_found_combo = None

        self.monitor_thread = None
        self.monitor_stop = threading.Event()
        self.serial_port = None
        self.flashing = False

        self._build_ui()
        self.refresh_ports()

    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}

        row = ttk.Frame(self); row.pack(fill="x", **pad)
        ttk.Label(row, text="COM port:").pack(side="left")
        self.com_combo = ttk.Combobox(row, textvariable=self.com_var, width=18, state="readonly")
        self.com_combo.pack(side="left", padx=6)
        ttk.Button(row, text="Refresh", command=self.refresh_ports).pack(side="left")
        ttk.Label(row, text="(ESP on CP210x = COM13)").pack(side="left", padx=6)

        row = ttk.Frame(self); row.pack(fill="x", **pad)
        ttk.Label(row, text="Bin folder:").pack(side="left")
        ttk.Entry(row, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Browse", command=self.browse_folder).pack(side="left")

        grp = ttk.LabelFrame(self, text="Detected binaries (auto)"); grp.pack(fill="x", **pad)
        for label, var in (("Bootloader", self.bootloader_var),
                           ("Partitions", self.partitions_var),
                           ("App (.ino.bin)", self.app_var),
                           ("boot_app0", self.boot_app0_var)):
            r = ttk.Frame(grp); r.pack(fill="x", **pad)
            ttk.Label(r, text=label + ":", width=16).pack(side="left")
            ttk.Entry(r, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
            ttk.Button(r, text="...", width=4,
                       command=lambda v=var: self.pick_file(v)).pack(side="left")

        ota = ttk.LabelFrame(self, text="OTA upload (ESP must already be running OTA firmware)")
        ota.pack(fill="x", **pad)
        r = ttk.Frame(ota); r.pack(fill="x", **pad)
        ttk.Label(r, text="ESP IP / hostname:", width=18).pack(side="left")
        self.ota_found_combo = ttk.Combobox(r, textvariable=self.ota_display_var, width=32,
                                            state="readonly")
        self.ota_found_combo.pack(side="left", padx=6)
        self.ota_found_combo.bind("<<ComboboxSelected>>", self.select_ota_device)
        ttk.Button(r, text="SEARCH", command=self.start_ota_discovery).pack(side="left", padx=4)
        ttk.Label(r, text="Port:").pack(side="left")
        ttk.Entry(r, textvariable=self.ota_port_var, width=7).pack(side="left", padx=6)
        ttk.Label(r, text="OTA password:").pack(side="left")
        password_entry = ttk.Entry(r, textvariable=self.ota_password_var, width=24, show="*")
        password_entry.pack(side="left", padx=6)
        self._add_edit_menu(password_entry)
        r = ttk.Frame(ota); r.pack(fill="x", **pad)
        ttk.Label(r, text="Application .bin:", width=18).pack(side="left")
        ttk.Entry(r, textvariable=self.app_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r, text="...", width=4,
                   command=lambda: self.pick_file(self.app_var)).pack(side="left")
        self.ota_btn = ttk.Button(ota, text="UPLOAD OTA", command=self.start_ota)
        self.ota_btn.pack(anchor="w", padx=10, pady=4)

        row = ttk.Frame(self); row.pack(fill="x", **pad)
        self.flash_btn = ttk.Button(row, text="FLASH (no compile)", command=self.start_flash)
        self.flash_btn.pack(side="left", padx=4)
        self.monitor_btn = ttk.Button(row, text="Start Serial Monitor", command=self.toggle_monitor)
        self.monitor_btn.pack(side="left", padx=4)
        ttk.Label(row, text="Monitor baud: %d" % BAUD_MONITOR).pack(side="left", padx=8)

        ttk.Label(self, text="Log / Serial output:").pack(anchor="w", padx=6)
        self.log = scrolledtext.ScrolledText(self, height=22, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=4)

    def _add_edit_menu(self, entry):
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
        menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: entry.event_generate("<<SelectAll>>"))

        def popup(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind("<Button-3>", popup)

    def log_write(self, msg):
        self.log.insert("end", msg)
        self.log.see("end")

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.com_combo["values"] = ports
        if ports and not self.com_var.get():
            for p in serial.tools.list_ports.comports():
                if "cp210" in (p.description or "").lower():
                    self.com_var.set(p.device)
                    return
            self.com_var.set(ports[0])

    def browse_folder(self):
        d = filedialog.askdirectory(title="Select folder containing .bin files")
        if d:
            self.folder_var.set(d)
            det = detect_bins(d)
            if det["bootloader"]:
                self.bootloader_var.set(det["bootloader"])
            if det["partitions"]:
                self.partitions_var.set(det["partitions"])
            if det["app"]:
                self.app_var.set(det["app"])
            if det["boot_app0"]:
                self.boot_app0_var.set(det["boot_app0"])
            self.log_write("Detected in %s\n" % d)
            for k, v in det.items():
                self.log_write("  %s: %s\n" % (k, v))

    def pick_file(self, var):
        p = filedialog.askopenfilename(title="Select .bin file",
                                      filetypes=[("Binary", "*.bin"), ("All", "*.*")])
        if p:
            var.set(p)

    def toggle_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        port = self.com_var.get()
        if not port:
            messagebox.showwarning("No port", "Select a COM port first.")
            return
        self.monitor_stop.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(port,), daemon=True)
        self.monitor_thread.start()
        self.monitor_btn.config(text="Stop Serial Monitor")
        self.log_write("--- Serial monitor started on %s @ %d ---\n" % (port, BAUD_MONITOR))

    def stop_monitor(self, wait=True):
        self.monitor_stop.set()
        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except Exception:
                pass
            self.serial_port = None
        if wait and self.monitor_thread is not None:
            self.monitor_thread.join(timeout=2)
        self.monitor_thread = None
        self.monitor_btn.config(text="Start Serial Monitor")
        self.log_write("--- Serial monitor stopped ---\n")

    def _monitor_loop(self, port):
        try:
            sp = serial.Serial(port, BAUD_MONITOR, timeout=0.5)
            self.serial_port = sp
        except Exception as e:
            self.log_write("Monitor open error: %s\n" % e)
            return
        while not self.monitor_stop.is_set():
            try:
                data = sp.read(512)
                if data:
                    text = data.decode("utf-8", errors="replace")
                    self.log.insert("end", text)
                    self.log.see("end")
            except Exception as e:
                self.log_write("Monitor read error: %s\n" % e)
                break
        try:
            sp.close()
        except Exception:
            pass
        self.serial_port = None

    def start_flash(self):
        if self.flashing:
            return
        port = self.com_var.get()
        if not port:
            messagebox.showwarning("No port", "Select a COM port first.")
            return
        bootloader = self.bootloader_var.get().strip()
        partitions = self.partitions_var.get().strip()
        app = self.app_var.get().strip()
        boot_app0 = self.boot_app0_var.get().strip()
        for name, val in (("bootloader", bootloader), ("partitions", partitions),
                          ("app", app), ("boot_app0", boot_app0)):
            if not val or not os.path.isfile(val):
                messagebox.showerror("Missing file", "Missing or invalid %s file." % name)
                return

        ok = messagebox.askokcancel(
            "Enter download mode",
            "Before flashing:\n\n"
            "1. Close Serial Monitor if it is open.\n"
            "2. First try clicking OK normally (auto-reset).\n"
            "3. If this board does not auto-reset, hold BOOT, press/release EN,\n"
            "   keep BOOT held, then click OK. Release BOOT after Connecting\n"
            "   changes to writing.\n\n"
            "The serial monitor will be paused during flashing.")
        if not ok:
            return

        was_monitoring = (self.monitor_thread is not None and self.monitor_thread.is_alive())
        if was_monitoring:
            self.stop_monitor(wait=True)

        self.flashing = True
        self.flash_btn.config(state="disabled")
        threading.Thread(target=self._flash_worker,
                         args=(port, bootloader, partitions, boot_app0, app, was_monitoring),
                         daemon=True).start()

    def _flash_worker(self, port, bootloader, partitions, boot_app0, app, restart_monitor):
        try:
            operation, before, after, flash_mode, flash_freq, flash_size = esptool_cli_options()
            cmd = [ESPTOOL, "--chip", "esp32", "--port", port, "--baud", str(BAUD_FLASH),
                   "--before", before, "--after", after, operation, "-z",
                   flash_mode, "dio", flash_freq, "80m", flash_size, "4MB",
                   "0x1000", bootloader,
                   "0x8000", partitions,
                   "0xe000", boot_app0,
                   "0x10000", app]
            self.log_write("\n=== FLASH START (%s @ %d) ===\n" % (port, BAUD_FLASH))
            self.log_write(" ".join(cmd) + "\n")
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            for line in proc.stdout:
                self.log.insert("end", line)
                self.log.see("end")
            proc.wait()
            if proc.returncode == 0:
                self.log_write("\n=== FLASH OK ===\n")
                messagebox.showinfo("Flash complete", "Flashing finished successfully.")
            else:
                self.log_write("\n=== FLASH FAILED (code %d) ===\n" % proc.returncode)
                messagebox.showerror("Flash failed", "esptool exited with code %d." % proc.returncode)
        except Exception as e:
            self.log_write("Flash error: %s\n" % e)
            messagebox.showerror("Flash error", str(e))
        finally:
            self.flashing = False
            self.flash_btn.config(state="normal")
            if restart_monitor:
                self.start_monitor()

    def start_ota(self):
        if self.flashing:
            return
        if not ESPOTA or not os.path.isfile(ESPOTA):
            messagebox.showerror("Missing espota.py", "Arduino ESP32 package espota.py was not found.")
            return
        host = self.ota_host_var.get().strip()
        app = self.app_var.get().strip()
        password = self.ota_password_var.get()
        try:
            port = int(self.ota_port_var.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid OTA port", "OTA port must be 1..65535.")
            return
        if not host:
            messagebox.showwarning("Missing ESP address", "Enter the ESP IP or hostname.")
            return
        if not app or not os.path.isfile(app):
            messagebox.showerror("Missing application", "Select the compiled application .bin file.")
            return
        if not messagebox.askokcancel(
                "Upload over OTA",
                "The ESP must be powered, connected to the same LAN, and running OTA firmware.\n\n"
                "Continue uploading the application image?"):
            return
        self.flashing = True
        self.ota_btn.config(state="disabled")
        threading.Thread(target=self._ota_worker,
                         args=(host, port, password, app), daemon=True).start()

    def _ota_worker(self, host, port, password, app):
        try:
            local_ip = local_ipv4_for_target(host)
            ota_runner = [ESPOTA] if ESPOTA.lower().endswith(".exe") else [sys.executable, ESPOTA]
            cmd = ota_runner + ["-i", host, "-p", str(port),
                   "-P", str(OTA_HOST_PORT), "-f", app]
            if local_ip:
                cmd += ["-I", local_ip]
            if password:
                cmd += ["-a", password]
            self.log_write("\n=== OTA START (%s:%d) ===\n" % (host, port))
            self.log_write("Application: %s\n" % app)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            for line in proc.stdout:
                self.log.insert("end", line)
                self.log.see("end")
            proc.wait()
            if proc.returncode == 0:
                self.log_write("\n=== OTA OK ===\n")
                messagebox.showinfo("OTA complete", "Firmware uploaded successfully.")
            else:
                self.log_write("\n=== OTA FAILED (code %d) ===\n" % proc.returncode)
                messagebox.showerror("OTA failed", "espota.py exited with code %d." % proc.returncode)
        except Exception as e:
            self.log_write("OTA error: %s\n" % e)
            messagebox.showerror("OTA error", str(e))
        finally:
            self.flashing = False
            self.ota_btn.config(state="normal")

    def start_ota_discovery(self):
        self.log_write("\n=== Searching local network for OTA ESP devices ===\n")
        threading.Thread(target=self._ota_discovery_worker, daemon=True).start()

    def _ota_discovery_worker(self):
        try:
            port = int(self.ota_port_var.get().strip())
            devices = arduino_tool_mdns_devices()
            if not devices:
                devices = arduino_cli_network_devices()
            found = [ip for _, ip in devices]
            if not found:
                found = scan_ota_hosts(port)
                devices = [("ESP32 OTA at " + ip, ip) for ip in found]
            self.after(0, lambda: self._show_ota_devices(devices, port))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self.log_write("OTA search error: %s\n" % msg))

    def _show_ota_devices(self, devices, port):
        if self.ota_found_combo is not None:
            self.ota_found_combo["values"] = [label for label, _ in devices]
        if devices:
            self.ota_display_var.set(devices[0][0])
            self.ota_host_var.set(devices[0][1])
            self.log_write("Found OTA device(s) on port %d: %s\n" %
                           (port, ", ".join(label for label, _ in devices)))
        else:
            self.log_write("No OTA device found on the local /24 network.\n")

    def select_ota_device(self, _event=None):
        label = self.ota_display_var.get()
        if " at " in label:
            self.ota_host_var.set(label.rsplit(" at ", 1)[1])

    def on_close(self):
        self.stop_monitor(wait=False)
        self.destroy()


if __name__ == "__main__":
    app = FlasherApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
