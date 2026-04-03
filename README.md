# Raspberry Pi Video Capture Utilities

Small utility scripts for exploring a Raspberry Pi based capture workflow.

## Utilities

- `scripts/list_capture_formats.py`
  - Lists connected V4L2 capture devices and the video formats supported by a selected device.
- `scripts/run_capture_test.py`
  - Runs an interactive capture test with `ffmpeg` and prints a lightweight live status view.

## Intended Environment

These scripts are meant to run on Linux, especially Raspberry Pi OS.

## Dependencies

- Python 3.9+
- `v4l2-ctl`
- `ffmpeg`

On Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y v4l-utils ffmpeg python3
```

## Examples

List devices and formats:

```bash
python3 scripts/list_capture_formats.py
python3 scripts/list_capture_formats.py --device /dev/video0
```

Run a guided test:

```bash
python3 scripts/run_capture_test.py
```

Non-interactive test:

```bash
python3 scripts/run_capture_test.py \
  --device /dev/video0 \
  --video-size 1280x720 \
  --framerate 60 \
  --pixel-format mjpeg \
  --duration 30 \
  --output /media/pi/CAPTURE
```
