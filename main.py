from pipeline.ingest.detector import detect_capture_type


def main():
    capture_type = detect_capture_type("captures/test_photo")
    print("Detected:", capture_type.value)


if __name__ == "__main__":
    main()