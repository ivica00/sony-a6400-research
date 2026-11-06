#!/usr/bin/env python3
"""
Interactive Live Debug Terminal for Sony ILCE-6400 over Wi-Fi.
Auto-discovers camera via UDP broadcast or port 2323 scan, then bridges
an interactive root shell (/bin/sh) with real-time bidirectional I/O.
"""

import sys
import os
import socket
import select
import threading
import time

TCP_PORT = 2323
UDP_PORT = 2324
SUBNET_PREFIX = "192.168.100."

def listen_for_beacon(timeout=5):
    print(f"[*] Listening for camera UDP beacon on port {UDP_PORT}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', UDP_PORT))
    s.settimeout(timeout)
    try:
        data, addr = s.recvfrom(1024)
        ip = addr[0]
        print(f"[+] Camera beacon received from {ip}: {data.decode('utf-8', errors='ignore').strip()}")
        s.close()
        return ip
    except socket.timeout:
        s.close()
        return None

def scan_subnet(timeout=0.1):
    print(f"[*] Scanning {SUBNET_PREFIX}0/24 on port {TCP_PORT}...")
    found_ip = None

    def check_ip(ip):
        nonlocal found_ip
        if found_ip:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((ip, TCP_PORT))
            s.close()
            found_ip = ip
        except Exception:
            pass

    threads = []
    for i in range(2, 255):
        ip = f"{SUBNET_PREFIX}{i}"
        t = threading.Thread(target=check_ip, args=(ip,))
        t.daemon = True
        threads.append(t)
        t.start()
        if len(threads) >= 50:
            for th in threads:
                th.join()
            threads = []
        if found_ip:
            break

    for th in threads:
        th.join()

    return found_ip

def interactive_session(cam_ip):
    print(f"\n[+] Connecting to Sony ILCE-6400 root shell at {cam_ip}:{TCP_PORT}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((cam_ip, TCP_PORT))
    print("[***] CONNECTED! Press Ctrl+C or type 'exit' to disconnect. [***]\n")

    # Background reader thread
    running = True
    def reader():
        while running:
            try:
                data = s.recv(4096)
                if not data:
                    print("\n[*] Connection closed by camera.")
                    break
                sys.stdout.write(data.decode('utf-8', errors='replace'))
                sys.stdout.flush()
            except Exception:
                break

    t = threading.Thread(target=reader)
    t.daemon = True
    t.start()

    # Main writer loop
    try:
        while running:
            line = sys.stdin.readline()
            if not line:
                break
            s.sendall(line.encode('utf-8'))
            if line.strip() == 'exit':
                break
    except KeyboardInterrupt:
        print("\n[*] Disconnecting...")
    finally:
        running = False
        s.close()

def main():
    target_ip = None
    if len(sys.argv) > 1:
        target_ip = sys.argv[1]
    else:
        # 1. Listen for beacon
        target_ip = listen_for_beacon(timeout=3)
        # 2. If not found, scan subnet
        if not target_ip:
            target_ip = scan_subnet(timeout=0.15)

    if not target_ip:
        print("[-] Camera not found on Wi-Fi yet.")
        print("[i] Ensure camera is powered on and connected to 'HUAWEI-g9XR'.")
        print("[i] You can also specify IP directly: python tools/cam_live_terminal.py <IP>")
        return 1

    interactive_session(target_ip)
    return 0

if __name__ == '__main__':
    sys.exit(main())
