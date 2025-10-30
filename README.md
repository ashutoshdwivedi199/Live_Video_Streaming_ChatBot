# Live Video Streaming with Optional Object Detection

This project demonstrates real-time video streaming from a webcam using Python and GStreamer, with two modes:
1. Basic live video streaming (`start_stream.py`)
2. Live video streaming with object detection and tracking (`object_stream.py`)

Both modes stream video using HLS (HTTP Live Streaming) and serve it via a local HTTP server.

---

## Project Files

| File Name         | Description                                                                 |
|------------------|-----------------------------------------------------------------------------|
| `start_stream.py` | Streams raw webcam feed using GStreamer without any object detection.       |
| `object_stream.py`| Streams webcam feed with YOLOv5-based object detection and centroid tracking.|

---

## Features
### Common Features
- Real-time webcam capture at 20 FPS.
- HLS streaming using GStreamer.
- Local HTTP server on port `8554` to serve `.m3u8` playlist and `.ts` segments.
- Automatic cleanup of HLS files after streaming ends.
- Config-driven parameters to customize encoder, HLS, and detection behavior.

### Object Detection Mode (`object_stream.py`)
- Uses **YOLOv5n** for lightweight object detection.
- Tracks objects using a custom **CentroidTracker**.
- Annotates frames with bounding boxes, class labels, and confidence scores.
- Filters detections with confidence ≥ 0.75 (configurable).
- Performs detection every 10 frames (configurable) for performance optimization :: to make it lightweight for streaming.

## Configuration
Added a config.json file to the project root to control encoding, HLS, and object detection behavior. 
- Example:

`{`
  `"use_object_detection": true,`
  `"bitrate": 2048,`
  `"speed_preset": "ultrafast",`
  `"target_duration": 5,`
  `"max_files": 30,`
  `"segment_location": "./hls/segment_%05d.ts",`
  `"playlist_location": "./hls/test.m3u8",`
  `"playlist_root": "http://localhost:8554/hls/",`
  `"frame_width": 640,`
  `"frame_height": 480,`
  `"model_path": "yolov5n.pt",`
  `"frames_interval": 20,`
  `"detection_conf": 0.75,`
  `"obj_detection_interval": 10`
`}`

- To run through json config 'stream_config.json': please run main.py file. However, both start_stream.py & object_stream.py can also be run independently.

## Requirements
Install the required Python packages:

Also ensure:
- **GStreamer** is installed and `gst-launch-1.0` is available in your system PATH.
- Python 3.7 or higher is installed.

## How to Run

### 1. Basic Streaming (no detection)
python start_stream.py

### 2. Streaming with Object Detection
python object_stream.py

## Notes

- `ksvideosrc` is used in `start_stream.py` (Windows-specific). Replace with `v4l2src` for Linux or `avfvideosrc` for macOS.
- `object_stream.py` uses `cv2.VideoCapture(0, cv2.CAP_DSHOW)` for webcam access.
- GStreamer pipeline parameters (bitrate, segment duration, etc.) can be tuned for performance.

## Acknowledgments

- [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
- [GStreamer](https://gstreamer.freedesktop.org/)
- [OpenCV](https://opencv.org/)
