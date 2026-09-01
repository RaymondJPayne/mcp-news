"""Container healthcheck. Exits 0 when the API answers."""
import sys
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8378/api/health", timeout=10) as r:
            return 0 if r.status == 200 else 1
    except Exception:
        return 1

if __name__ == "__main__":
    sys.exit(main())
