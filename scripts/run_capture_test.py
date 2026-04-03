#!/usr/bin/env python3
"""Run an interactive ffmpeg capture test for a V4L2 device."""

from __future__ import annotations

import argparse
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DeviceInfo:
    name: str
    path: str


@dataclass
class CaptureStats:
    fps: str = "-"
    speed: str = "-"
    frame: str = "-"
    size_kb: str = "-"
    bitrate: str = "-"
    dropped: int = 0


STATUS_RE = re.compile(
    r"frame=\s*(?P<frame>\S+).*?fps=\s*(?P<fps>\S+).*?size=\s*(?P<size>\S+).*?time=\s*(?P<time>\S+).*?bitrate=\s*(?P<bitrate>\S+).*?speed=\s*(?P<speed>\S+)",
    re.IGNORECASE,
)


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


def choose_device(devices: list[DeviceInfo]) -> str:
    if not devices:
        print("No V4L2 devices found.", file=sys.stderr)
        sys.exit(1)

    print("Available capture devices:")
    for index, device in enumerate(devices, start=1):
        print(f"  [{index}] {device.path}  {device.name}")

    while True:
        answer = input("Select device number: ").strip()
        if not answer.isdigit():
            print("Enter a numeric selection.")
            continue
        index = int(answer)
        if 1 <= index <= len(devices):
            return devices[index - 1].path
        print("Selection out of range.")


def prompt_value(label: str, default: str) -> str:
    answer = input(f"{label} [{default}]: ").strip()
    return answer or default


def sanitize_token(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("/", "-")
    normalized = normalized.replace(" ", "-")
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-") or "unknown"


def build_output_path(
    output_arg: str | None,
    pixel_format: str,
    video_size: str,
    framerate: str,
    container: str,
) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    format_token = sanitize_token(pixel_format)
    size_token = sanitize_token(video_size)
    fps_token = sanitize_token(framerate)
    filename = f"capture-test-{timestamp}-{size_token}-{fps_token}fps-{format_token}.{container}"

    if not output_arg:
        return filename

    output_path = Path(output_arg).expanduser()
    if output_path.exists() and output_path.is_dir():
        return str(output_path / filename)

    return str(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device")
    parser.add_argument("--pixel-format")
    parser.add_argument("--video-size")
    parser.add_argument("--framerate")
    parser.add_argument("--duration", type=int)
    parser.add_argument("--output")
    parser.add_argument("--video-codec", default="libx264")
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--crf", type=int, default=23)
    parser.add_argument(
        "--container",
        default="mkv",
        choices=["mkv", "mp4"],
        help="Used when output path is omitted.",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> dict[str, str | int]:
    devices = list_devices()
    device = args.device or choose_device(devices)
    pixel_format = args.pixel_format or prompt_value("Pixel format", "mjpeg")
    video_size = args.video_size or prompt_value("Video size", "1280x720")
    framerate = args.framerate or prompt_value("Frame rate", "60")
    duration = args.duration or int(prompt_value("Duration in seconds", "30"))
    output = build_output_path(
        args.output,
        pixel_format=pixel_format,
        video_size=video_size,
        framerate=framerate,
        container=args.container,
    )

    return {
        "device": device,
        "pixel_format": pixel_format,
        "video_size": video_size,
        "framerate": framerate,
        "duration": duration,
        "output": output,
        "video_codec": args.video_codec,
        "preset": args.preset,
        "crf": args.crf,
    }


def read_cpu_temp() -> str:
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        raw = thermal_path.read_text(encoding="utf-8").strip()
        return f"{int(raw) / 1000:.1f}C"
    except (OSError, ValueError):
        return "-"


def read_meminfo() -> tuple[str, str]:
    total_kb = 0
    avail_kb = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
    except OSError:
        return "-", "-"

    if total_kb <= 0:
        return "-", "-"

    used_pct = ((total_kb - avail_kb) / total_kb) * 100
    return f"{used_pct:.1f}%", f"{avail_kb // 1024} MiB"


def read_loadavg() -> str:
    try:
        with open("/proc/loadavg", "r", encoding="utf-8") as handle:
            return handle.read().split()[0]
    except OSError:
        return "-"


def read_disk_free(output_path: str) -> str:
    try:
        usage = shutil.disk_usage(Path(output_path).resolve().parent)
        return f"{usage.free / (1024 ** 3):.1f} GiB"
    except OSError:
        return "-"


def print_config(config: dict[str, str | int]) -> None:
    print("\nCapture configuration:")
    for key in [
        "device",
        "pixel_format",
        "video_size",
        "framerate",
        "duration",
        "video_codec",
        "preset",
        "crf",
        "output",
    ]:
        print(f"  {key}: {config[key]}")


def build_ffmpeg_command(config: dict[str, str | int]) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-stats",
        "-f",
        "v4l2",
        "-input_format",
        str(config["pixel_format"]),
        "-framerate",
        str(config["framerate"]),
        "-video_size",
        str(config["video_size"]),
        "-i",
        str(config["device"]),
        "-t",
        str(config["duration"]),
        "-an",
        "-c:v",
        str(config["video_codec"]),
        "-preset",
        str(config["preset"]),
        "-crf",
        str(config["crf"]),
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(config["output"]),
    ]


def parse_status_line(line: str, stats: CaptureStats) -> None:
    match = STATUS_RE.search(line)
    if match:
        stats.frame = match.group("frame")
        stats.fps = match.group("fps")
        stats.size_kb = match.group("size")
        stats.bitrate = match.group("bitrate")
        stats.speed = match.group("speed")
        return

    lower = line.lower()
    if "drop" in lower:
        stats.dropped += 1


def status_loop(process: subprocess.Popen[str], stats: CaptureStats, config: dict[str, str | int]) -> None:
    start = time.monotonic()
    while process.poll() is None:
        elapsed = time.monotonic() - start
        mem_used, mem_free = read_meminfo()
        line = (
            f"\rrec {elapsed:6.1f}s"
            f" | fps {stats.fps:>6}"
            f" | frame {stats.frame:>7}"
            f" | size {stats.size_kb:>8}"
            f" | bitrate {stats.bitrate:>10}"
            f" | speed {stats.speed:>6}"
            f" | drops {stats.dropped:>3}"
            f" | load {read_loadavg():>4}"
            f" | mem {mem_used:>6}"
            f" | free {mem_free:>8}"
            f" | temp {read_cpu_temp():>5}"
            f" | disk {read_disk_free(str(config['output'])):>8}"
        )
        print(line, end="", flush=True)
        time.sleep(1.0)
    print()


def ffmpeg_reader(process: subprocess.Popen[str], stats: CaptureStats) -> None:
    assert process.stderr is not None
    for line in process.stderr:
        parse_status_line(line.strip(), stats)


def main() -> int:
    require_binary("v4l2-ctl")
    require_binary("ffmpeg")

    args = parse_args()
    config = build_config(args)
    print_config(config)

    output_parent = Path(str(config["output"])).expanduser().resolve().parent
    output_parent.mkdir(parents=True, exist_ok=True)

    command = build_ffmpeg_command(config)
    print("\nStarting capture test...\n")

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stats = CaptureStats()
    reader = threading.Thread(target=ffmpeg_reader, args=(process, stats), daemon=True)
    reader.start()

    try:
        status_loop(process, stats, config)
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)

    return_code = process.wait()
    reader.join(timeout=1.0)

    if return_code == 0:
        print(f"Capture test finished successfully: {config['output']}")
        return 0

    print(f"Capture test failed with exit code {return_code}.", file=sys.stderr)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
