import subprocess
import os
import signal
import psutil  # ✅ Requires: pip install psutil

stream_proc = None
object_proc = None
http_proc = None

def kill_process_tree(proc):
    if proc and proc.poll() is None:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
            proc.wait()
        except Exception as e:
            print(f"Error killing process tree: {e}")

def launch_http_server():
    global http_proc
    if http_proc is None or http_proc.poll() is not None:
        http_proc = subprocess.Popen(
            ["python", "-m", "http.server", "8554"],
            cwd=os.getcwd(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ HTTP server started on port 8554.")

def stop_http_server():
    global http_proc
    if http_proc and http_proc.poll() is None:
        kill_process_tree(http_proc)
        http_proc = None
        print("🛑 HTTP server stopped.")

def start_stream():
    global stream_proc
    stop_object_stream()
    if stream_proc is None or stream_proc.poll() is not None:
        stream_proc = subprocess.Popen(
            ["python", "start_stream.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ Regular stream started.")
        launch_http_server()

def start_object_stream():
    global object_proc
    stop_stream()
    if object_proc is None or object_proc.poll() is not None:
        object_proc = subprocess.Popen(
            ["python", "object_stream.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("✅ Object detection stream started.")
        launch_http_server()

def stop_stream():
    global stream_proc
    if stream_proc and stream_proc.poll() is None:
        kill_process_tree(stream_proc)
        stream_proc = None
        print("🛑 Regular stream stopped.")

def stop_object_stream():
    global object_proc
    if object_proc and object_proc.poll() is None:
        kill_process_tree(object_proc)
        object_proc = None
        print("🛑 Object detection stream stopped.")

def stop_all():
    stop_stream()
    stop_object_stream()
    stop_http_server()
    print("🧹 All streams and server stopped.")