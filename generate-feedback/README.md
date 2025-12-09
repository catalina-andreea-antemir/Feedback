# Feeback Generator

## Purpose

This project is designed to generate realistic, anonymized feedback datasets in JSON format. The primary goal is to provide reliable, non-sensitive data for testing the main project's data processing and analysis scripts.

## Content

- `main.py`
    - This scripts loads course metadata from   Pickle files and uses predefined logic to create simulated student feedback in `feedback-contents` directory.

- `convert_script.py`
    - Utility script for converting data, typically between Pickle and JSON formats.

- `config.conf`
    - Configuration file containing settings for running the script.

- `pickles/`
    - Directory containing the necessary input Pickle files:
    - `feedbacks.p` - Contains the list of existing feedbacks from IDs and their configurations.
    - `courses.p` - Contains metadata about courses: ID, name, category ID
    - `categories.p` - Contains metadata about course categories.
    - `courses4categories.p` - Contains metadata about relationship between courses and categories.

- `jsons/`
    - Directory containing the JSON versions of the metadata files (e.g., `categories.json`, `courses.json`, etc.).

- `feedback-contents/`
    - This is the directory that will be created automatically after running the python script. It contains the resulting feedback JSON files.
    - e.g. `1000.json`.

## Necessities for running the script

- Python Version: 3.x

- The script requires the existence of the following Pickle files: `feedbacks.p`, `courses.p`, `categories.p`, `courses4categories.p`

### Virtual Environment Setup

- It is recommended to use a vitual environment (venv) to isolate projects dependencies.

- Creating venv steps:
    - create venv: `python3 -m venv venv`
    - activate venv:
        - Linux/macOS: `source venv/bin/activate`
        - Windows: `venv\Scripts\activate`
    - make sure that the necessary libraries are installed; the script uses `json`, `os`, `pickle`, `random`; they can be installed with `pip install <library>`

- When you finished working with the project, deactivate the environment: `deactivate` or `exit`

### Running the Script

- `python3 main.py` : this version will take the interval for the number of students that is set in the script `config.conf`

- `python3 main.py --min-students <val_min> --max-students <val_max>` : the interval for the number of students will be set as [val_min, val_max]; those 2 values can be whatever positive number you want with the condition that val_min <= val_max