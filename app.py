from flask import Flask, request, render_template
import threading
import stream_controller

app = Flask(__name__, static_folder='hls')

@app.route("/hls/<path:filename>")
def hls_files(filename):
    return send_from_directory("hls", filename, mimetype="application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else None)

def get_bot_response(user_input):
    user_input = user_input.lower().strip()

    if user_input == "y":
        threading.Thread(target=stream_controller.start_object_stream, daemon=True).start()
        return "✅ Object detection stream started with HTTP server."
    elif user_input == "n":
        threading.Thread(target=stream_controller.start_stream, daemon=True).start()
        return "✅ Regular stream started with HTTP server."
    elif user_input == "e":
        stream_controller.stop_all()
        return "🛑 All streams and server stopped."
    else:
        return "❌ Invalid input. Please enter Y, N, or E."

@app.route("/", methods=["GET", "POST"])
def chatbot():
    response = ""
    if request.method == "POST":
        user_input = request.form["user_input"]
        response = get_bot_response(user_input)
    return render_template("index.html", response=response)

if __name__ == "__main__":
    app.run(debug=True)