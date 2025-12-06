# Feeback Generator

## Purpose

This project is designed to generate realistic, anonymized feedback datasets in JSON format. The primary goal is to provide reliable, non-sensitive data for testing the main project's data processing and analysis scripts.

## Content

- ```main.py```
    - This scripts loads course metadata from   Pickle files and uses predefined logic to create simulated student feedback in ```feedback-contents``` directory.

- ```feedbacks.p```
    - Contains the list of existing feedbacks from IDs and their configurations.

- ```courses.p```
    - Contains metadata about courses: ID, name, category ID

- ```categories.p```
    - Contains metadata about course categories.

- ```feedback-contents```
    - This is the directory that will be created automatically after running the python script. It contains the resulting feedback JSON files.
    - e.g. ```1000.json```.

## Necessities for running the script

- Python Version: 3.x

- The script requires the existence of the following Pickle files: ```feedbacks.p```, ```courses.p```, ```categories.p```

### Virtual Environment Setup

- It is recommended to use a vitual environment (venv) to isolate projects dependencies.

- Creating venv steps:
    - create venv: ```python3 -m venv venv```
    - activate venv:
        - Linux/macOS: ```source venv/bin/activate```
        - Windows: ```venv\Scripts\activate```
    - make sure that the necessary libraries are installed; the script uses ```json```, ```os```, ```pickle```, ```random```; they can be installed with ```pip install <library>```

- When you finished working with the project, deactivate the environment: ```deactivate``` or ```exit```

### Running the Script

- ```python3 main.py```

