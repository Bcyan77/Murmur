import sys
import multiprocessing


def main():
    multiprocessing.freeze_support()
    from murmur.app import MurmurApp

    app = MurmurApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
