"""
check_frozen_readers.py
-----------------------
Reads the JSON of `PyAT --engine --json info` on stdin and fails unless the executable says it can import every reader a release must have (TDT tanks,
Excel workbooks). PyATCLI loads those packages by name when a file of that type is opened (PyATCLI/_optional.py), which PyInstaller cannot see by reading the
code: they are named in PhysicsAnalysis.spec's hiddenimports, and this proves the build bundled them.

    dist\\PyAT.exe --engine --json info | python packaging/check_frozen_readers.py
"""

import json
import sys

REQUIRED = ("tdt", "excel", "oxysoft", "csv", "pt2")       # the text field study's language model is left out of the executable on purpose


def main(text):
    start = text.find("{")                       # the JSON (pretty-printed over many lines), after anything the program printed first
    if start < 0:
        print("::error::the executable printed no JSON: it did not run as the engine")
        return 1
    info, _ = json.JSONDecoder().raw_decode(text[start:])
    result = info.get("result", info)
    optional = result.get("optional")
    if optional is None:
        print("::error::the executable's info has no 'optional' readers: it was built with a PyATCLI older than the one that reports them")
        return 1
    missing = [extra for extra in REQUIRED if not optional.get(extra)]
    print(f"frozen: {result.get('frozen')}; readers: " + ", ".join(f"{extra} {'yes' if ok else 'NO'}" for extra, ok in optional.items()))
    if not result.get("frozen"):
        print("::error::this is not the frozen executable")
        return 1
    if missing:
        print(f"::error::the executable cannot import what these file types need: {', '.join(missing)} (name the packages in PhysicsAnalysis.spec's hiddenimports)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))
