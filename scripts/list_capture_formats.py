#!/usr/bin/env python3
"""List V4L2 capture devices and supported formats."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class DeviceInfo:
    name: str
    path: str


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True)


def require_binary(name: str) -> None:
    if shutil.which(name):
        return
    print(f"Missing required command: {name}", file=sys.stderr)
    sys.exit(1)


def list_devices() -> list[DeviceInfo]:
    result = run_command(["v4l2-ctl", "--list-devices"])
    if result.returncode != 0:
        print(result.stderr.strip() or "Failed to list V4L2 devices.", file=sys.stderr)
        sys.exit(result.returncode or 1)

    devices: list[DeviceInfo] = []
    current_name: str | None = None

    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if not line:
            current_name = None
            continue

        if not raw_line.startswith("\t"):
            current_name = line.rstrip(":")
            continue

        path = line.strip()
        if current_name and path.startswith("/dev/video"):
            devices.append(DeviceInfo(name=current_name, path=path))

    return devices


def print_devices(devices: list[DeviceInfo]) -> None:
    if not devices:
        print("No V4L2 video devices found.")
        return

    print("Available capture devices:")
    for index, device in enumerate(devices, start=1):
        print(f"  [{index}] {device.path}  {device.name}")


def print_formats(device: str) -> int:
    result = run_command(["v4l2-ctl", f"--device={device}", "--list-formats-ext"])
    if result.returncode != 0:
        print(result.stderr.strip() or f"Failed to query formats for {device}.", file=sys.stderr)
        return result.returncode or 1

    print(f"\nFormats for {device}:")
    print(result.stdout.strip())
    return 0


def resolve_device(device_arg: str | None, devices: list[DeviceInfo]) -> str | None:
    if device_arg:
        return device_arg
    if len(devices) == 1:
        return devices[0].path
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="V4L2 device path, for example /dev/video0")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list devices without printing supported formats.",
    )
    return parser.parse_args()


def main() -> int:
    require_binary("v4l2-ctl")
    args = parse_args()
    devices = list_devices()
    print_devices(devices)

    if args.list_only:
        return 0

    device = resolve_device(args.device, devices)
    if not device:
        if not devices:
            return 1
        print("\nSelect a device with --device /dev/videoN to view formats.")
        return 0

    return print_formats(device)


if __name__ == "__main__":
    raise SystemExit(main())
