import json
import pickle
import os
import glob
import sys

INPUT_DIR = "jsons"
PICKLE_DIR = "pickles"


def convert_json_to_pickle(file_type):
    json_file_path = os.path.join(INPUT_DIR, f"{file_type}.json")
    pickle_file_path = os.path.join(PICKLE_DIR, f"{file_type}.p")

    if not os.path.exists(json_file_path):
        return False

    if not os.path.exists(PICKLE_DIR):
        os.makedirs(PICKLE_DIR)

    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # JSON object keys are ALWAYS strings, but courses4categories is keyed by Moodle
        # category id, which is an int everywhere else (retrieve-feedback/courses4categories.py
        # builds it as `mapping[category['id']]`). Without this coercion the round-trip
        # through JSON silently turns 7 into "7", and processor.courses4category(7) --
        # which swallows the KeyError with a bare `except: return []` -- reports ZERO
        # courses for every category.
        if file_type == "courses4categories":
            data = {int(k): v for k, v in data.items()}

        with open(pickle_file_path, "wb") as f:
            pickle.dump(data, f)

        return True

    except Exception:
        return False


def main():
    if not os.path.exists(INPUT_DIR):
        print(f"'{INPUT_DIR}/' not found -- nothing to convert.")
        return 1

    search_pattern = os.path.join(INPUT_DIR, "*.json")
    json_files = sorted(glob.glob(search_pattern))

    failed = []
    for json_path in json_files:
        filename = os.path.basename(json_path)
        file_type = os.path.splitext(filename)[0]

        if not convert_json_to_pickle(file_type):
            failed.append(filename)

    # Silence here used to mean "no pickle, no message, and main.py fails later with a
    # confusing FILE NOT FOUND". Say which file broke.
    if failed:
        print(f"FAILED to convert: {', '.join(failed)}")
        return 1
    print(f"Converted {len(json_files)} file(s) to '{PICKLE_DIR}/'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
