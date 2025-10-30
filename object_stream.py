import os
import cv2
import subprocess
import time
import json
import numpy as np
from scipy.spatial import distance as dist
from collections import OrderedDict
from ultralytics import YOLO

def load_config(config_path='stream_config.json'):
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load config: {e} !!!")
        return {
            "bitrate": 2048,
            "speed_preset": "ultrafast",
            "target_duration": 5,                               ## Gstreamer aim to create new segments of length target_duration.
            "max_files": 30,                                    ## Provides bigger playback with tradeoff on disk size
            "segment_location": "./hls/%05d.ts",
            "playlist_location": "./hls/test.m3u8",
            "playlist_root": "http://localhost:8554/hls/",
            "frames_interval": 15,                              ## Tradeoff between viewing fluidity and latency
            "detection_conf": 0.75,                             ## Thresholding for model detection => due to varied luminiousity and other factors
            "obj_detection_interval": 10                        ## Tradeoff between detection and latency:
        }                                                       ## Config["obj_detection_interval"] >= 6. Where 3 is fixed for model out & 3 is atleast for tracking.

http_proc = None
def launch_http_server():
    global http_proc
    if http_proc is None or http_proc.poll() is not None:
        http_proc = subprocess.Popen(
            ["python", "-m", "http.server", "8554"],
            cwd=os.getcwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("HTTP server started on port 8554.")

class CentroidTracker:
    def __init__(self, max_disappeared=10):
        self.next_object_id = 0
        self.objects = OrderedDict()
        self.disappeared = OrderedDict()
        self.max_disappeared = max_disappeared
        self.rects = OrderedDict()

    def register(self, centroid, rect):
        self.objects[self.next_object_id] = centroid
        self.rects[self.next_object_id] = rect
        self.disappeared[self.next_object_id] = 0
        #print(f"[Register] Object {self.next_object_id} initialized at centroid {centroid}")
        self.next_object_id += 1

    def deregister(self, object_id):
        #print(f"[Deregister] Object {object_id} removed from tracking")
        del self.objects[object_id]
        del self.rects[object_id]
        del self.disappeared[object_id]

    def update(self, rects):
        if len(rects) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)
            return self.rects

        input_centroids = []
        for (x1, y1, x2, y2) in rects:
            cX = int((x1 + x2) / 2.0)
            cY = int((y1 + y2) / 2.0)
            input_centroids.append((cX, cY))

        if len(self.objects) == 0:
            for centroid, rect in zip(input_centroids, rects):
                self.register(centroid, rect)
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())
            D = dist.cdist(np.array(object_centroids), np.array(input_centroids))
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                object_id = object_ids[row]
                self.objects[object_id] = input_centroids[col]
                self.rects[object_id] = rects[col]
                self.disappeared[object_id] = 0
                #print(f"[Tracking] Object {object_id} updated to centroid {input_centroids[col]}")
                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(0, D.shape[0])).difference(used_rows)
            unused_cols = set(range(0, D.shape[1])).difference(used_cols)

            for row in unused_rows:
                object_id = object_ids[row]
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self.deregister(object_id)

            for col in unused_cols:
                self.register(input_centroids[col], rects[col])

        return self.rects

def start_object_detection_stream():
    print("******************     LIVE VIDEO STREAMING WITH OBJECT DETECTION     ******************")
    os.makedirs('./hls', exist_ok=True)

    model = YOLO('yolov5n.pt')

    config = load_config()
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["frame_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["frame_height"])
    cap.set(cv2.CAP_PROP_FPS, config["frames_interval"])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print("Error: Cannot open webcam")
        return

    gst_command = [
        r'gst-launch-1.0.exe',
        'fdsrc', '!',
        'rawvideoparse', 'format=bgr', f'width={config["frame_width"]}', f'height={config["frame_height"]}', f'framerate={config["frames_interval"]}/1',
        '!', 'videoconvert',
        '!', 'x264enc', f'tune=zerolatency', f'bitrate={config["bitrate"]}', f'speed-preset={config["speed_preset"]}',
        '!', 'mpegtsmux',
        '!', 'hlssink',
        f'location={config["segment_location"]}',
        f'playlist-location={config["playlist_location"]}',
        f'playlist-root={config["playlist_root"]}',
        f'target-duration={config["target_duration"]}',
        f'max-files={config["max_files"]}'
    ]

    gst_process = subprocess.Popen(gst_command, stdin=subprocess.PIPE)

    frame_interval = 1 / config["frames_interval"]
    count = 0
    tracker = CentroidTracker()
    boxes = []
    launch_http_server()
    id_to_label = {}
    try:
        while True:
            istracking = 0
            start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                print("Error: Failed to read frame")
                break
    
            if frame.shape[:2] != (config["frame_height"], config["frame_width"]):
                frame = cv2.resize(frame, (config["frame_width"], config["frame_height"]))
    
            if count % config["obj_detection_interval"] < 3:
                istracking = 0
                results = model.predict(frame, stream=False, verbose=False)[0]
                boxes = []
                labels = []

                for box, cls, conf in zip(results.boxes.xyxy.cpu().numpy(),
                              results.boxes.cls.cpu().numpy(),
                              results.boxes.conf.cpu().numpy()):
                    if conf >= config["detection_conf"]:  # Only track confident detections
                        x1, y1, x2, y2 = map(int, box[:4])
                        label = model.names[int(cls)]
                        boxes.append((x1, y1, x2, y2))
                        labels.append(label)
                        #print(f"[Detection] Frame {count}: {label} detected with confidence {conf:.2f} at ({x1}, {y1}), ({x2}, {y2})")
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"Model: {label} {conf:.2f}", (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

                tracked = tracker.update(boxes)

                # Map object IDs to labels
                for object_id, label in zip(tracker.rects.keys(), labels):
                    id_to_label[object_id] = label
            else:
                istracking = 1
                tracked = tracker.update(boxes)
            
                for object_id, rect in tracked.items():
                    if object_id not in id_to_label:
                        continue  # Skip if label is unknown
            
                    x1, y1, x2, y2 = rect
                    cX = int((x1 + x2) / 2.0)
                    cY = int((y1 + y2) / 2.0)
                    label = id_to_label[object_id]
                    #print(f"[Tracking] Frame {count}: {label} at centroid ({cX}, {cY})")
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                    #cv2.circle(frame, (cX, cY), 4, (0, 0, 255), -1)
                    cv2.putText(frame, f"Tracking: {label}", (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

    
            annotated = frame
            gst_process.stdin.write(annotated.tobytes())
            count += 1
            elapsed = time.time() - start_time
            time.sleep(max(0, frame_interval - elapsed))

            try:
                gst_process.stdin.write(annotated.tobytes())
            except Exception as e:
                print(f"GStreamer write error: {e}")
                break

    finally:
        cap.release()
        if gst_process.stdin:
            gst_process.stdin.close()
        gst_process.wait()
        cv2.destroyAllWindows()

        # Delete all files in ./hls/
        hls_dir = './hls'
        try:
            for filename in os.listdir(hls_dir):
                file_path = os.path.join(hls_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            print("Cleaned up HLS segment files.")
        except Exception as e:
            print(f"Error cleaning up HLS files: {e}")

if __name__ == "__main__":
    start_object_detection_stream()