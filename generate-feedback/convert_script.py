import json
import pickle
import os
import glob

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

        with open(pickle_file_path, "wb") as f:
            pickle.dump(data, f)

        return True

    except Exception:
        return False


def main():
    if not os.path.exists(INPUT_DIR):
        return

    search_pattern = os.path.join(INPUT_DIR, "*.json")
    json_files = glob.glob(search_pattern)

    for json_path in json_files:
        filename = os.path.basename(json_path)
        file_type = os.path.splitext(filename)[0]

        convert_json_to_pickle(file_type)


if __name__ == "__main__":
    main()
