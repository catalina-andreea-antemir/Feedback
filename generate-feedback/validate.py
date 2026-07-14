#!/usr/bin/env python3

"""Prove the generated dataset is actually consumable. Exits non-zero if it isn't.

This re-implements the acceptance rules of BOTH consumers, because the generator repo
cannot import them. Every check below corresponds to a real way the pipeline rejects or
silently corrupts data:

  25 responses            process-feedback/processor.py  is_course_feedback / add_json
                          web-interface/taxonomy.py      _parse_feedback_file
  rawval is a str         processor.convert_value catches only ValueError -- a JSON null
                          raises TypeError and crashes the run
  likert in "1".."5"      "0" decodes to 0 in processor (dropped) but to 6 in taxonomy
                          (kept, off-scale) -- the two consumers would disagree
  printval == rawval      processor reads names/text from rawval; taxonomy from printval
  slot 0 == shortname     processor keys courses by it; analysis/ and mappings/ join on it
  users file consistency  the completion-% denominator, and the titular/asistent roles

The pickles are read so a feedback file can be tied back to its COURSE. That matters: a
course may own several feedback forms, the web interface merges the attempts of all of
them, and enrolment is a property of the course -- so completion % has to be checked
against the course's total, never one file's.

Usage:  ./validate.py [--out DIR] [--pickles DIR]
"""

import argparse
import json
import os
import pickle
import sys
from collections import defaultdict

from slots import LIKERT, MIRRORED, RAW_INT, SLOTS

RAW_INT_BOUNDS = {"expected_grade": (5, 10), "part": (3, 5), "assign_time": (1, 25)}


def load_course_index(pickles_dir):
    """-> {feedback_id: (course_id, shortname)}, so every check can reach the real course."""
    with open(os.path.join(pickles_dir, "courses.p"), "rb") as f:
        courses = pickle.load(f)
    with open(os.path.join(pickles_dir, "feedbacks.p"), "rb") as f:
        feedbacks = pickle.load(f)
    by_id = {c["id"]: c for c in courses if "id" in c}
    index = {}
    for fb in feedbacks:
        course = by_id.get(fb.get("course"))
        if course:
            index[fb["id"]] = (course["id"], course.get("shortname"))
    return index


def check_feedback_file(path, errors, expected_shortname):
    name = os.path.basename(path)

    def fail(message):
        errors.append(f"{name}: {message}")

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:  # the malformed export is what we exist to REPORT
        fail(f"unreadable: {e}")
        return None

    for key in ("attempts", "totalattempts", "anonattempts", "totalanonattempts", "warnings"):
        if key not in data:
            fail(f"missing top-level key '{key}'")
            return None

    attempts = data["anonattempts"]
    if not isinstance(attempts, list):
        fail("anonattempts must be a list")
        return None
    if data["totalanonattempts"] != len(attempts):
        fail("totalanonattempts != len(anonattempts)")

    prof, assistants = None, set()
    for att in attempts:
        responses = att.get("responses", [])
        # Checked on EVERY attempt, not just the first: is_course_feedback only inspects
        # anonattempts[0], but add_json indexes keys[i] for all of them.
        if len(responses) != 25:
            fail(f"attempt {att.get('id')} has {len(responses)} responses, need 25")
            continue
        if not all(isinstance(r, dict) for r in responses):
            fail(f"attempt {att.get('id')} has a non-object response")
            continue

        for i, ((key, qname, kind), r) in enumerate(zip(SLOTS, responses)):
            raw, printval = r.get("rawval"), r.get("printval")
            if r.get("name") != qname:
                fail(f"slot {i} name {r.get('name')!r} != {qname!r}")
            if not isinstance(raw, str) or not isinstance(printval, str):
                fail(f"slot {i} ({key}) rawval/printval must both be strings")
                continue
            if key in MIRRORED and printval != raw:
                fail(f"slot {i} ({key}) printval != rawval")
            if kind is LIKERT:
                if raw not in {"1", "2", "3", "4", "5"}:
                    fail(f"slot {i} ({key}) likert rawval {raw!r} not in 1..5")
                elif not 1 <= 6 - int(raw) <= 5:  # the consumers' own decode
                    fail(f"slot {i} ({key}) decodes off-scale")
            elif kind is RAW_INT:
                try:
                    value = int(raw)
                except ValueError:
                    fail(f"slot {i} ({key}) rawval {raw!r} is not an int")
                    continue
                lo, hi = RAW_INT_BOUNDS[key]
                if not lo <= value <= hi:
                    fail(f"slot {i} ({key}) {value} outside {(lo, hi)}")

        # Slot 0 must be the course's REAL shortname: processor keys courses by this
        # value and the analysis/ + mappings/ scripts join on it.
        got = responses[0].get("rawval")
        if got != expected_shortname:
            fail(f"slot 0 is {got!r}, expected the course shortname {expected_shortname!r}")
        if prof is None:
            prof = responses[1].get("rawval")
        elif responses[1].get("rawval") != prof:
            fail(f"attempts disagree on the titular: {prof!r} vs {responses[1].get('rawval')!r}")
        assistants.add(responses[2].get("rawval"))

    return {"attempts": len(attempts), "prof": prof, "assistants": assistants}


def load_users_file(path, errors):
    """-> {"students": int, "roles": {fullname: 'titular'|'asistent'}}, using exactly the
    fields the consumers read (processor.users4course_by_role, taxonomy._parse_users_file)."""
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            users = json.load(f)
    except (OSError, ValueError) as e:
        errors.append(f"users/{name}: unreadable: {e}")
        return None
    if not isinstance(users, list):
        errors.append(f"users/{name}: must be a JSON list (core_enrol_get_enrolled_users)")
        return None

    roles, students = {}, 0
    for u in users:
        shortnames = {r.get("shortname") for r in u.get("roles", [])}
        if "student" in shortnames:
            students += 1
        if "editingteacher" in shortnames:
            roles[u.get("fullname")] = "titular"
        elif "asistent" in shortnames:
            roles[u.get("fullname")] = "asistent"
    return {"students": students, "roles": roles}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out")
    p.add_argument("--pickles", default="pickles")
    args = p.parse_args()

    contents_dir = os.path.join(args.out, "feedback_contents")
    users_dir = os.path.join(args.out, "users")
    for d in (contents_dir, users_dir):
        if not os.path.isdir(d):
            print(f"FAIL: '{d}' does not exist. The web interface ignores the export "
                  f"entirely unless BOTH feedback_contents/ and users/ are present.")
            return 1
    try:
        course_of = load_course_index(args.pickles)
    except (OSError, ValueError) as e:
        print(f"FAIL: cannot read the pickles in '{args.pickles}': {e}")
        return 1

    errors = []

    # Group the feedback files by COURSE: the web interface merges every form of a course,
    # so enrolment and staff have to be checked against the course's totals, not one file's.
    by_course = defaultdict(lambda: {"attempts": 0, "prof": None, "assistants": set(), "files": []})
    for fname in sorted(os.listdir(contents_dir)):
        if not fname.endswith(".json"):
            continue
        try:
            fid = int(os.path.splitext(fname)[0])
        except ValueError:
            errors.append(f"{fname}: filename is not a feedback id")
            continue
        if fid not in course_of:
            errors.append(f"{fname}: no course owns feedback {fid}")
            continue
        course_id, shortname = course_of[fid]

        summary = check_feedback_file(os.path.join(contents_dir, fname), errors, shortname)
        if not summary:
            continue
        agg = by_course[course_id]
        agg["attempts"] += summary["attempts"]
        agg["assistants"] |= summary["assistants"]
        agg["files"].append(fname)
        if summary["prof"]:
            if agg["prof"] and agg["prof"] != summary["prof"]:
                errors.append(f"course {course_id}: two titulari across its forms")
            agg["prof"] = summary["prof"]

    n_users = 0
    for course_id, agg in sorted(by_course.items()):
        # Joined by COURSE ID, not by teacher name: a titular owns several courses, so a
        # name-based join can silently check the wrong course's enrolment.
        upath = os.path.join(users_dir, f"{course_id}.json")
        if not os.path.exists(upath):
            errors.append(f"course {course_id}: no users/{course_id}.json (completion % "
                          f"has no denominator)")
            continue
        uf = load_users_file(upath, errors)
        if not uf:
            continue
        n_users += 1

        if uf["students"] < agg["attempts"]:
            errors.append(
                f"course {course_id}: {uf['students']} students enrolled but "
                f"{agg['attempts']} responded across {len(agg['files'])} form(s) "
                f"-- completion would exceed 100%"
            )
        if agg["prof"] and uf["roles"].get(agg["prof"]) != "titular":
            errors.append(f"course {course_id}: titular {agg['prof']!r} is not an "
                          f"editingteacher in its users file")
        for a in agg["assistants"]:
            if uf["roles"].get(a) != "asistent":
                errors.append(f"course {course_id}: asistent {a!r} missing or miscast "
                              f"in its users file")

    total = sum(a["attempts"] for a in by_course.values())
    print(f"checked {len(by_course)} courses, {total} attempts, {n_users} users files")

    if errors:
        print(f"\nFAILED with {len(errors)} error(s):")
        for e in errors[:40]:
            print(f"  - {e}")
        if len(errors) > 40:
            print(f"  ... and {len(errors) - 40} more")
        return 1

    print("OK: every attempt has 25 responses; likert in 1..5; printval==rawval on the "
          "mirrored slots; slot 0 is the real shortname; every course has a users file "
          "with enough enrolled students and the right staff roles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
