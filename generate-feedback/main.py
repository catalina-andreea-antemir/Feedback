import pickle
import json
import os
import random

# Macrouri pt limitele numarului de studenti
MIN_STUDENTS = 20
MAX_STUDENTS = 100


def load_pickle(filename):
    # Incarca fisierele .p
    if not os.path.exists(filename):
        print(f"FILE NOT FOUND: '{filename}'.")
        return []
    with open(filename, 'rb') as f:
        return pickle.load(f)


def get_random_response(question_type):
    # Genereaza raspunsuri random respectand logica formularelor de feedback
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
    # Construieste structura JSON pentru un singur formular
    anon_attempts = []

    base_attempt_id = feedback_id
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

        # Sablonul pt afisarea datelor
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
    feedbacks = load_pickle('feedbacks.p')
    courses = load_pickle('courses.p')
    categories = load_pickle('categories.p')

    courses_map = {c['id']: c for c in courses}
    categories_map = {cat['id']: cat for cat in categories}

    output_dir = 'feedback_contents'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Folder created: '{output_dir}'")

    print(f"Loaded {len(feedbacks)} feedback forms and {len(courses)} courses.")

    count = 0
    for fb in feedbacks:
        fb_id = fb.get('id')
        course_id = fb.get('course')

        if fb_id:
            # Se cauta cursul
            course_obj = courses_map.get(course_id)
            course_name = "Curs Necunoscut"
            category_name = ""

            if course_obj:
                course_name = course_obj.get('fullname', 'Curs Fara Nume')
                cat_id = course_obj.get('category')
                if cat_id and cat_id in categories_map:
                    category_name = categories_map[cat_id].get('name', '')

            # Compunere nume materie
            full_subject_name = course_name
            if category_name:
                full_subject_name += f" ({category_name})"

            # Date simulate
            teacher_name = "Prenume NUME"
            num_students = random.randint(MIN_STUDENTS, MAX_STUDENTS)

            # Generare Json
            json_data = generate_feedback_data(fb_id, full_subject_name, teacher_name, num_students)

            # Salvare fisier
            filename = os.path.join(output_dir, f"{fb_id}.json")
            with open(filename, 'w', encoding='utf-8') as f:
                # feedback-uri cu diacritice, deci folosim ensure_ascii=False
                json.dump(json_data, f, indent=2, ensure_ascii=False)

            count += 1
            if count % 50 == 0:
                print(f"Generating {count} files...")

    print(f"Generated {count} files in '{output_dir}'.")


if __name__ == "__main__":
    main()