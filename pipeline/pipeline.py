from pipeline.ingest.capture import load_capture


def run_pipeline(input_path: str):
    capture = load_capture(input_path)

    print("Capture ready")
    print("Path:", capture.path)
    print("Type:", capture.capture_type.value)
    print("Photos loaded:", len(capture.photos))
    print("Tier:", capture.metadata.tier)   