import os
import cv2
import subprocess
import time
import json
import numpy as np
from scipy.spatial import distance as dist
from collections import OrderedDict
from ultralytics import YOLO
import threading  # Added for scalability - allow running multiple streams in threads
import logging
import signal

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
            "obj_detection_interval": 10,                       ## Tradeoff between detection and latency:
            "frame_width": 640,  								## Added explicit defaults for width/height for scalability
            "frame_height": 480,
            "debug_network_outage": false,
            "debug_camera_failure": false,
            "debug_gst_failure": false,
            "debug_segment_delivery": false
        }

http_proc = None
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
        
def launch_http_server():
    """Launch local HTTP server for HLS playback."""
    global http_proc
    if http_proc is None or http_proc.poll() is not None:
        try:
            http_proc = subprocess.Popen(
                ["python", "-m", "http.server", "8554"],
                cwd=os.getcwd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("HTTP server started on port 8554.")
        except Exception as e:
            print(f"[Error] Failed to start HTTP server: {e}")

def shutdown_http_server():
    """Gracefully shut down the HTTP server if running."""
    global http_proc
    if http_proc and http_proc.poll() is None:
        print("[Info] Shutting down HTTP server...")
        os.killpg(os.getpgid(http_proc.pid), signal.SIGTERM)  # ✅ Delta: kill process group
        http_proc.wait()
        http_proc = None

def restart_gstreamer(config):
    """Reliability improvement:
    Restart GStreamer automatically if it crashes or pipe breaks."""
    try:
        gst_command = [
            r'gst-launch-1.0.exe',
            'fdsrc', '!',
            'rawvideoparse', 'format=bgr',
            f'width={config["frame_width"]}', f'height={config["frame_height"]}',
            f'framerate={config["frames_interval"]}/1',
            '!', 'videoconvert',
            '!', 'x264enc', f'tune=zerolatency', f'bitrate={config["bitrate"]}',
            f'speed-preset={config["speed_preset"]}',
            '!', 'mpegtsmux',
            '!', 'hlssink',
            f'location={config["segment_location"]}',
            f'playlist-location={config["playlist_location"]}',
            f'playlist-root={config["playlist_root"]}',
            f'target-duration={config["target_duration"]}',
            f'max-files={config["max_files"]}'
        ]
        return subprocess.Popen(gst_command, stdin=subprocess.PIPE)
    except Exception as e:
        print(f"[Error] Failed to start GStreamer: {e}")
        return None

def start_object_detection_stream():
    print("******************     LIVE VIDEO STREAMING WITH OBJECT DETECTION     ******************")
    os.makedirs('./hls', exist_ok=True)

    model = YOLO('yolov5n.pt')

    config = load_config()
    launch_http_server()

    # Enhancement: Start HTTP server watchdog thread to monitor network health
    def monitor_http_server():
        import requests

        logging.basicConfig(filename="http_watchdog.log", level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(message)s")

        # Enhanced Debug features: Print playlist URL
        #print(f"[Debug] Monitoring playlist URL: {config['playlist_location'].replace('./hls', 'http://localhost:8554/hls')}")
        playlist_url = config["playlist_location"].replace("./hls", "http://localhost:8554/hls")
        retry_count = 0
        max_retries = 3
        retry_interval = 10

        while True:
            try:
                if config.get("debug_network_outage", False):
                    raise requests.ConnectionError("Simulated network outage")

                r = requests.get(playlist_url, timeout=2)
                if r.status_code != 200:
                    logging.warning(f"Playlist returned status {r.status_code}. Retrying...")
                    retry_count += 1
                else:
                    retry_count = 0
            except Exception as e:
                logging.warning(f"HTTP server unreachable: {e}")
                retry_count += 1

            if retry_count >= max_retries:
                logging.error("HTTP server failed multiple times. Restarting server...")
                print("[Watchdog] Restarting HTTP server after repeated failures...")
                launch_http_server()
                retry_count = 0

            time.sleep(retry_interval)

    import threading
    threading.Thread(target=monitor_http_server, daemon=True).start()

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    # Enhanced Debug features: Print camera config parameters
    #print(f"[Debug] Camera config - Width: {config['frame_width']}, Height: {config['frame_height']}, FPS: {config['frames_interval']}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["frame_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["frame_height"])
    cap.set(cv2.CAP_PROP_FPS, config["frames_interval"])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print("Error: Cannot open webcam")
        return

    gst_process = restart_gstreamer(config)
    frame_interval = 1 / config["frames_interval"]
    count = 0
    tracker = CentroidTracker()
    boxes = []
    id_to_label = {}
    count_camera_debug = 0
    camera_failure_log = open("debug_camera_failure.txt", "a")
    try:
        while True:
            istracking = 0
            start_time = time.time()

            # Enhanced Debug features: simulate camera failure
            if config.get("debug_camera_failure", False) and count_camera_debug % 50 == 0:
                msg = f"[Debug] Simulating camera failure at frame {count_camera_debug}::{count}\n"
                print(msg.strip())
                camera_failure_log.write(msg)
                camera_failure_log.flush()
                ret = False
                frame = None
            else:
                ret, frame = cap.read()
            
            count_camera_debug += 1
            if not ret:
                print("[Warning] Frame not received. Retrying camera...")
                time.sleep(1)
                # Reliability: Attempt to reinitialize camera on failure
                cap.release()
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                continue

            # Reliability: Restart GStreamer if process has exited
            if gst_process.poll() is not None:
                print("[Warning] GStreamer process stopped. Restarting...")
                gst_process = restart_gstreamer(config)
                if gst_process is None:
                    print("[Critical] Failed to restart GStreamer. Exiting...")
                break
    
            if frame.shape[:2] != (config["frame_height"], config["frame_width"]):
                frame = cv2.resize(frame, (config["frame_width"], config["frame_height"]))

            # Enhanced Debug features: Print object detection interval
            #print(f"[Debug] Object detection interval: {config['obj_detection_interval']}")
            if count % config["obj_detection_interval"] < 3:
                istracking = 0
                results = model.predict(frame, stream=False, verbose=False)[0]
                boxes = []
                labels = []

                # Enhanced Debug features: Print detection confidence threshold
                #print(f"[Debug] Detection confidence threshold: {config['detection_conf']}")
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
                    #cX = int((x1 + x2) / 2.0)
                    #cY = int((y1 + y2) / 2.0)
                    label = id_to_label[object_id]
                    #print(f"[Tracking] Frame {count}: {label} at centroid ({cX}, {cY})")
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                    #cv2.circle(frame, (cX, cY), 4, (0, 0, 255), -1)
                    cv2.putText(frame, f"Tracking: {label}", (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

    
            try:
                gst_process.stdin.write(frame.tobytes())

                # Enhanced Debug features: simulate GStreamer failure
                if config.get("debug_gst_failure", False) and count % 100 == 0:
                    print("[Debug] Simulating GStreamer failure...")
                    gst_process.kill()

            except Exception as e:
                print(f"[Error] GStreamer write failed: {e}. Restarting stream...")
                gst_process = restart_gstreamer(config)
                continue  # Retry loop
            # Enhancement: Log segment delivery status (basic check)
            segment_path = config["segment_location"] % count

            # Enhanced Debug features: simulate segment delivery issue
            if config.get("debug_segment_delivery", False) and count % 60 == 0:
                fake_segment = config["segment_location"] % (count + 9999)
                print(f"[Debug] Simulating missing segment: {fake_segment}")
                if not os.path.exists(fake_segment):
                    print(f"[Warning] Simulated segment {fake_segment} not found.")
            elif not os.path.exists(segment_path):
                print(f"[Warning] Segment {segment_path} not found. Possible delivery issue.")

            count += 1
            elapsed = time.time() - start_time
            time.sleep(max(0, frame_interval - elapsed))

    except KeyboardInterrupt: ## in case the interrupt is signalled.
        print("\n[Info] Stopping stream gracefully...")
        shutdown_http_server()
        cap.release()
        if gst_process and gst_process.stdin:
            gst_process.stdin.close()
        if gst_process:
            gst_process.wait()
        cv2.destroyAllWindows()
        try:
            for filename in os.listdir(hls_dir):
                file_path = os.path.join(hls_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            print("Cleaned up HLS segment files.")
        except Exception as e:
            print(f"Error cleaning up HLS files: {e}")
            
    finally: ## in case the code breaks at the run time
        cap.release()
        if gst_process and gst_process.stdin:
            gst_process.stdin.close()
        if gst_process:
            gst_process.wait()
        cv2.destroyAllWindows()
        shutdown_http_server()
        try:
            for filename in os.listdir(hls_dir):
                file_path = os.path.join(hls_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            print("Cleaned up HLS segment files.")
        except Exception as e:
            print(f"Error cleaning up HLS files: {e}")

# Scalability improvement:
# Allow launching multiple parallel camera streams using threads if needed.
if __name__ == "__main__":
    t1 = threading.Thread(target=start_object_detection_stream)
    t1.start()
    t1.join()