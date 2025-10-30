import subprocess
import os
import shutil
import json

http_proc = None

def load_config(config_path='stream_config.json'):
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f" Failed to load config: {e} !!! ")
        return {
            "bitrate": 512,
            "speed_preset": "superfast",
            "target_duration": 5,
            "max_files": 5,
            "segment_location": "./hls/segment_%05d.ts",
            "playlist_location": "./hls/test.m3u8",
            "playlist_root": "http://localhost:8554/hls/"
        }

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
        
def start_stream():
    print("******************     LIVE VIDEO STREAMING WITHOUT OBJECT DETECTION     ******************")
    config = load_config()
    gst_command = (
        f'gst-launch-1.0 ksvideosrc ! '
        f'videoconvert ! '
        f'x264enc tune=zerolatency bitrate={config["bitrate"]} speed-preset={config["speed_preset"]} ! '
        f'mpegtsmux ! '
        f'hlssink location={config["segment_location"]} '
        f'playlist-location={config["playlist_location"]} '
        f'playlist-root={config["playlist_root"]} '
        f'target-duration={config["target_duration"]} max-files={config["max_files"]}'
    )
    launch_http_server()
    try:
        print("Starting GStreamer pipeline...")
        subprocess.run(gst_command, shell=True)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        hls_dir = './hls'
        if os.path.exists(hls_dir):
            print("Cleaning up HLS directory...")
            for filename in os.listdir(hls_dir):
                file_path = os.path.join(hls_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as cleanup_error:
                    print(f"Failed to delete {file_path}: {cleanup_error}")
            print("Cleanup complete.")

if __name__ == "__main__":
    start_stream()