from pipeline.ingest.types import CaptureType


def main():
    print(CaptureType.PHOTO.value)
    print(CaptureType.VIDEO.value)
    print(CaptureType.LIDAR.value)


if __name__ == "__main__":
    main()