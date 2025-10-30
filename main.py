import json

def load_config(path='stream_config.json'):
    with open(path, 'r') as f:
        config = json.load(f)
    return config

# Example usage
config = load_config()
#print(config["bitrate"])  # Access individual values

if config["use_object_detection"]:
    # Run object detection stream
    import object_stream
    object_stream.start_object_detection_stream()
else:
    # Run basic stream
    import start_stream
    start_stream.start_stream()