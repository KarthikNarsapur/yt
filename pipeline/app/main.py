"""Entry point: python -m app.main {script|render|publish}"""
import sys
import time


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    t0 = time.time()
    if stage == "script":
        from . import script_stage as s
    elif stage == "render":
        from . import render_stage as s
    elif stage == "publish":
        from . import publish_stage as s
    else:
        raise SystemExit("usage: python -m app.main {script|render|publish}")
    s.run()
    print(f"[{stage}] finished in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
