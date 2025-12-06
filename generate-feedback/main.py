import pickle
import json
import os
import random
import argparse
import configparser

def load_config(filename='config.ini'):
    # Default values in case config file is missing
    config_values = {
        'min_students': 20,
        'max_students': 100,
        'output_dir': 'feedback_contents'
    }

    if not os.path.exists(filename):
        print(f"Config file '{filename}' not found. Using internal defaults.")
        return config_values

    config = configparser.ConfigParser()
    config.read(filename)

    if 'GENERATOR' in config:
        # We use .getint for numbers and .get for strings
        config_values['min_students'] = config.getint('GENERATOR', 'MIN_STUDENTS', fallback=20)
        config_values['max_students'] = config.getint('GENERATOR', 'MAX_STUDENTS', fallback=100)
        config_values['output_dir'] = config.get('GENERATOR', 'OUTPUT_DIR', fallback='feedback_contents')

    return config_values

def parse_arguments(file_config):
    # The default values are taken from the loaded config file
    parser = argparse.ArgumentParser(description="Generate mock feedback data.")

    parser.add_argument(
        "--min-students",
        type=int,
        default=file_config['min_students'],
        help="Minimum number of students per course (overwrites config)"
    )
    parser.add_argument(
        "--max-students",
        type=int,
        default=file_config['max_students'],
        help="Maximum number of students per course (overwrites config)"
    )

    return parser.parse_args()

def load_pickle(filename):
    # Loads .p files
    if not os.path.exists(filename):
        print(f"FILE NOT FOUND: '{filename}'.")
        return []
    with open(filename, 'rb') as f:
        return pickle.load(f)

def get_random_response(question_type):
    # Generates random responses respecting the feedback form logic
    if question_type == "grade":
        grade = random.randint(5, 10)
        return str(grade), str(grade)

    elif question_type == "likert":
        options = [
            {"raw": "1", "print": "5  - Complet de Acord"},
            {"raw": "2", "print": "4  - ..."},
            {"raw": "3", "print": "3  - ..."},
            {"raw": "4", "print": "2  - ..."},
            {"raw": "5", "print": "1  - Deloc de acord"}
        ]
        choice = random.choice(options)
        return choice["print"], choice["raw"]

    elif question_type == "percent":
        options = [
            {"raw": "5", "print": "80% .. 100%"},
            {"raw": "4", "print": "60% .. 80%"},
            {"raw": "3", "print": "40% .. 60%"}
        ]
        choice = random.choice(options)
        return choice["print"], choice["raw"]

    return "", ""

def generate_feedback_data(feedback_id, course_name, teacher_name, num_students):
    # Builds the JSON structure for a single feedback form
    anon_attempts = []

    base_attempt_id = feedback_id * 100
    base_response_id = feedback_id * 200

    current_response_global_counter = base_response_id

    questions_structure = [
        ("Subject", "fixed", course_name),
        ("Teacher", "fixed", teacher_name),
        ("Laboratory/seminar/project ...", "fixed", teacher_name),
        ("Is your assessment of this ...", "likert", ""),
        ("What grade do you expect to...", "grade", ""),
        ("Is the general workload in ...", "likert", ""),
        ("Location / hardware and ...", "likert", ""),
        ("The approximate number of ...", "percent", ""),
        ("Does the course tutor have ...", "likert", ""),
        ("Was the teaching method ...", "likert", ""),
        ("Did the course stimulate ...", "likert", ""),
        ("Other personal comments or ...", "text", "")
    ]

    for i in range(num_students):
        responses = []
        current_attempt_id = base_attempt_id + i

        # Template for data display
        for q_name, q_type, q_default in questions_structure:
            entry = {
                "id": current_response_global_counter,
                "name": q_name,
                "printval": "",
                "rawval": ""
            }

            if q_type == "fixed":
                entry["printval"] = q_default
                entry["rawval"] = q_default
            elif q_type == "text":
                val = "feedback scris" if random.random() > 0.8 else ""
                entry["printval"] = val
                entry["rawval"] = val
            else:
                p_val, r_val = get_random_response(q_type)
                entry["printval"] = p_val
                entry["rawval"] = r_val

            responses.append(entry)
            current_response_global_counter += 1

        anon_attempts.append({
            "id": current_attempt_id,
            "courseid": 0,
            "number": i + 1,
            "responses": responses
        })

    return {
        "attempts": [],
        "totalattempts": 0,
        "anonattempts": anon_attempts,
        "totalanonattempts": len(anon_attempts),
        "warnings": []
    }

def main():
    # 1. Load config from file first
    file_config = load_config()

    # 2. Parse arguments (using file values as defaults)
    args = parse_arguments(file_config)

    # 3. Use the final values
    min_students = args.min_students
    max_students = args.max_students
    output_dir = file_config['output_dir']

    # Validation
    if min_students > max_students:
        print(f"Minimum students ({min_students}) cannot be greater than maximum students ({max_students}).")
        return

    print(f"Starting data generation...")
    print(f"Configuration: Min={min_students}, Max={max_students}")
    print(f"Output Directory: '{output_dir}'")

    feedbacks = load_pickle('feedbacks.p')
    courses = load_pickle('courses.p')
    categories = load_pickle('categories.p')

    courses_map = {c['id']: c for c in courses}
    categories_map = {cat['id']: cat for cat in categories}

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Folder created: '{output_dir}'")

    print(f"Loaded {len(feedbacks)} feedback forms and {len(courses)} courses.")

    count = 0
    for fb in feedbacks:
        fb_id = fb.get('id')
        course_id = fb.get('course')

        if fb_id:
            # Find the course object
            course_obj = courses_map.get(course_id)
            course_name = "Curs Necunoscut"
            category_name = ""

            if course_obj:
                course_name = course_obj.get('fullname', 'Curs Fara Nume')
                cat_id = course_obj.get('category')
                if cat_id and cat_id in categories_map:
                    category_name = categories_map[cat_id].get('name', '')

            # Compose subject name
            full_subject_name = course_name
            if category_name:
                full_subject_name += f" ({category_name})"

            # Simulated data
            teacher_name = "Prenume NUME"
            num_students = random.randint(min_students, max_students)

            # Generate JSON
            json_data = generate_feedback_data(fb_id, full_subject_name, teacher_name, num_students)

            # Save file
            filename = os.path.join(output_dir, f"{fb_id}.json")
            with open(filename, 'w', encoding='utf-8') as f:
                # Feedbacks contain diacritics, so we use ensure_ascii=False
                json.dump(json_data, f, indent=2, ensure_ascii=False)

            count += 1
            if count % 50 == 0:
                print(f"Generating {count} files...")

    print(f"Generated {count} files in '{output_dir}'.")

if __name__ == "__main__":
    main()