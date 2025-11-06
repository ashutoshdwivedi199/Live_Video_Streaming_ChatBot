from flask import Flask, request, render_template, send_from_directory
import threading
import stream_controller
import os

app = Flask(__name__, static_folder='hls')

# Global chat log and stream state
chat_log = []
stream_lock = threading.Lock()
active_stream_thread = None  # Track current stream thread

# Ensure hls folder exists
os.makedirs("hls", exist_ok=True)

@app.route("/hls/<path:filename>")
def hls_files(filename):
    return send_from_directory("hls", filename,
                               mimetype="application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else None)

def get_bot_response(user_input):
    global active_stream_thread

    user_input = user_input.lower().strip()

    if user_input == "y":
        with stream_lock:
            if active_stream_thread is not None and active_stream_thread.is_alive():
                return "⚠️ Object detection stream is already running!"

            stream_controller.stop_all()  # Ensure clean state
            thread = threading.Thread(target=stream_controller.start_object_stream, daemon=True)
            thread.start()
            active_stream_thread = thread
        return "✅ Object detection stream started with HTTP server."

    elif user_input == "n":
        with stream_lock:
            if active_stream_thread is not None and active_stream_thread.is_alive():
                return "⚠️ Regular stream is already running!"

            stream_controller.stop_all()
            thread = threading.Thread(target=stream_controller.start_stream, daemon=True)
            thread.start()
            active_stream_thread = thread
        return "✅ Regular stream started with HTTP server."

    elif user_input == "e":
        with stream_lock:
            was_running = stream_controller.stop_all()
            active_stream_thread = None
        return "🛑 All streams and server stopped." if was_running else "ℹ️ No stream was running."

    else:
        return "❌ Invalid input. Please enter Y, N, or E."

@app.route("/", methods=["GET", "POST"])
def chatbot():
    global chat_log
    response = ""

    if request.method == "POST":
        user_input = request.form.get("user_input", "").strip()
        if user_input:  # Only process if not empty
            chat_log.append({"role": "user", "message": user_input})
            response = get_bot_response(user_input)
            chat_log.append({"role": "bot", "message": response})
    
    # On GET (page load/refresh), do NOT trigger anything
    return render_template("index.html", response=response, chat_log=chat_log)

@app.route("/clear")
def clear_chat():
    global chat_log
    chat_log = []
    return render_template("index.html", response="Chat cleared.", chat_log=chat_log)

if __name__ == "__main__":
    # NEVER start streams here — only on user command
    print("Flask server starting... Go to http://127.0.0.1:5000")
    print("Type Y → Object detection | N → Normal stream | E → Stop all")
    app.run(debug=True, threaded=True)