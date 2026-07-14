#!/usr/bin/env python3

"""Generate a synthetic feedback dataset that the pipeline can actually consume.

Outputs, under --out:

    feedback_contents/<feedback_id>.json   25-slot attempts   (process-feedback, web-interface)
    users/<course_id>.json                 enrolled users     (completion %, staff roles)
    groundtruth/sentiment.jsonl            free-text labels   (NOT read by the pipeline)
    groundtruth/courses.jsonl              the hidden latents (NOT read by the pipeline)
    manifest.json                          seed + "synthetic: true"

The two ground-truth files sit in their own directory precisely because the consumers
glob feedback_contents/ and users/ and parse strictly by position -- anything unexpected
in those two directories is a landmine. Nothing outside them is ever read.

See slots.py for the 25-slot contract and model.py for why the numbers look the way they
do. Run validate.py afterwards to prove the output is consumable.
"""

import argparse
import configparser
import json
import logging
import os
import pickle
import sys
from collections import defaultdict

import model
import names
import slots
import textbank

PICKLE_INPUT_DIR = "pickles"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# feedback_contents/ and users/ are the two directory names the consumers look for; the
# web interface hardcodes both and ignores the export unless they sit side by side. They
# are not configurable for that reason.
CONTENTS_DIR = "feedback_contents"
USERS_DIR = "users"
TRUTH_DIR = "groundtruth"

DEFAULTS = {
    # Absolute bounds on ENROLLED students. Wide by default: actual enrolment comes from
    # the course's level and year (model.BASE_ENROLLED), and a narrow band here would
    # flatten a 220-student first-year course and a 26-student master elective into the
    # same size, which is exactly the spread the response-rate threshold needs.
    "min_students": 8,
    "max_students": 400,
    "output_dir": "out",
    "min_rate": 0.025,
    "max_rate": 0.325,
    "seed": 1337,
    "category": 7,  # ACS. 0 = the whole platform (~9700 forms, GB-scale -- see README).
}


def load_config(filename="config.conf"):
    cfg = dict(DEFAULTS)
    if not os.path.exists(filename):
        logger.warning("Config file '%s' not found. Using internal defaults.", filename)
        return cfg
    parser = configparser.ConfigParser()
    parser.read(filename)
    if "GENERATOR" in parser:
        g = parser["GENERATOR"]
        cfg["min_students"] = g.getint("MIN_STUDENTS", fallback=cfg["min_students"])
        cfg["max_students"] = g.getint("MAX_STUDENTS", fallback=cfg["max_students"])
        cfg["output_dir"] = g.get("OUTPUT_DIR", fallback=cfg["output_dir"])
        cfg["min_rate"] = g.getfloat("MIN_RESPONSE_RATE", fallback=cfg["min_rate"])
        cfg["max_rate"] = g.getfloat("MAX_RESPONSE_RATE", fallback=cfg["max_rate"])
        cfg["seed"] = g.getint("SEED", fallback=cfg["seed"])
        cfg["category"] = g.getint("CATEGORY_ID", fallback=cfg["category"])
    return cfg


def parse_arguments(cfg):
    p = argparse.ArgumentParser(description="Generate synthetic Moodle feedback data.")
    p.add_argument("--min-students", type=int, default=cfg["min_students"],
                   help="Minimum ENROLLED students per course (was: attempts -- see README)")
    p.add_argument("--max-students", type=int, default=cfg["max_students"],
                   help="Maximum ENROLLED students per course")
    p.add_argument("--min-response-rate", type=float, default=cfg["min_rate"])
    p.add_argument("--max-response-rate", type=float, default=cfg["max_rate"])
    p.add_argument("--seed", type=int, default=cfg["seed"],
                   help="Same seed => byte-identical output")
    p.add_argument("--out", default=cfg["output_dir"], help="Output root")
    p.add_argument("--category", type=int, default=cfg["category"],
                   help="Only courses under this Moodle category (7 = ACS; 0 = everything)")
    p.add_argument("--limit", type=int, default=0, help="Only the first N courses (smoke tests)")
    p.add_argument("--no-truth", action="store_true", help="Skip the ground-truth sidecar")
    p.add_argument("--report", action="store_true", help="Print dataset statistics when done")
    return p.parse_args()


def load_pickle(filename):
    path = os.path.join(PICKLE_INPUT_DIR, filename)
    if not os.path.exists(path):
        logger.error("FILE NOT FOUND: '%s'. Run convert_script.py first.", path)
        return []
    with open(path, "rb") as f:
        return pickle.load(f)


def category_subtree(categories, root_id):
    """The ids of `root_id` and everything under it, via Moodle's materialised `path`
    ('/1/7/941/...'), so we don't have to walk the tree."""
    if not root_id:
        return None  # no filtering
    prefix = f"/{root_id}/"
    keep = {root_id}
    for cat in categories:
        path = cat.get("path", "")
        if path.startswith(prefix) or path == f"/{root_id}":
            keep.add(cat["id"])
    return keep


def select_courses(courses, feedbacks, categories, category_id):
    """Courses that (a) have at least one feedback form and (b) sit in the wanted subtree.

    NOTE a course may own several feedback forms; we keep them all. The web interface
    merges attempts across a course's forms, and processor.feedback4course picks the
    fullest one -- either way the users file is written ONCE PER COURSE.
    """
    wanted = category_subtree(categories, category_id)
    fb_by_course = defaultdict(list)
    for fb in feedbacks:
        if "course" in fb and "id" in fb:
            fb_by_course[fb["course"]].append(fb["id"])

    selected = []
    for course in courses:
        cid = course.get("id")
        if cid not in fb_by_course:
            continue
        # The real dumps key this 'categoryid'. The previous generator read 'category',
        # which does not exist, so its category lookup silently always failed.
        if wanted is not None and course.get("categoryid") not in wanted:
            continue
        if not course.get("shortname"):
            continue
        selected.append(
            {
                "id": cid,
                "shortname": course["shortname"],
                # set(): feedbacks.p lists a handful of ids twice. Left as-is, the same
                # form is rendered twice and every one of its attempts is duplicated in
                # the ground-truth sidecar (the JSON file itself is just overwritten).
                "feedback_ids": sorted(set(fb_by_course[cid])),
            }
        )
    selected.sort(key=lambda c: c["id"])  # never rely on dump order: determinism
    return selected


def assign_staff(seed, courses):
    """A faculty roster, assigned to courses. Built from the FULL course list before
    --limit is applied, so a subset run keeps the same people on the same courses.

    Each titular takes ~2-3 courses so the Top-10 teacher rankings have something to
    aggregate -- and so that some of them legitimately fail the ">=15 responses" bar,
    which is how we know the threshold does any work at all.
    """
    rng = model.derive(seed, "staff")
    n_titulari = max(1, round(len(courses) / 2.5))
    n_asistenti = max(1, round(len(courses) * 1.25 / 2.5))
    roster = names.build_roster(rng, n_titulari + n_asistenti)
    titulari, asistenti = roster[:n_titulari], roster[n_titulari:]

    staff = {}
    for i, course in enumerate(courses):
        crng = model.derive(seed, "staff-of", course["id"])
        titular = titulari[i % n_titulari]
        n_assist = crng.randint(1, 4)
        pool = [asistenti[(i * 2 + k) % len(asistenti)] for k in range(n_assist)]
        staff[course["id"]] = {"titular": titular, "assistants": sorted(set(pool))}
    return staff, titulari, asistenti


def build_users_file(course_id, titular, assistants, enrolled):
    """The shape Moodle's core_enrol_get_enrolled_users returns: a JSON LIST.

    processor.users4course_by_role and taxonomy._parse_users_file both read only
    `fullname` and `roles[].shortname`. The titular/asistent names here MUST be the same
    strings written into the feedback attempts, or the web interface cannot resolve who
    is a titular and mis-attributes every row of the Top-10 pages.
    """
    users = [{"id": course_id * 1000, "fullname": titular, "roles": [{"shortname": "editingteacher"}]}]
    for i, name in enumerate(assistants, start=1):
        users.append({"id": course_id * 1000 + i, "fullname": name, "roles": [{"shortname": "asistent"}]})
    for i in range(enrolled):
        users.append(
            {
                "id": course_id * 1000 + 100 + i,
                "fullname": f"Student {course_id}-{i + 1:03d}",
                "roles": [{"shortname": "student"}],
            }
        )
    return users


def generate_course(seed, course, staff, cfg, collect):
    """Everything for one course: one file per feedback form, one users file."""
    titular = staff["titular"]
    assistants = staff["assistants"]
    titular_q = model.staff_quality(seed, "titular", titular)
    assistant_qs = [model.staff_quality(seed, "asistent", a) for a in assistants]

    plan = model.course_plan(seed, course["id"], course["shortname"], titular_q, assistant_qs, cfg)

    # A course can own several feedback forms, and the two consumers treat that
    # differently: the web interface MERGES the attempts of every form of a course, while
    # processor.feedback4course picks the single fullest form and ignores the rest. So
    # spreading a course's respondents across its forms would make the pipeline report a
    # fraction of the responses the dashboard reports, for the same course.
    #
    # Put every respondent on ONE form instead. The sibling forms are still written, empty:
    # processor.num_entries_in_feedback opens each of a course's forms to find the fullest,
    # with no guard, so an absent file is a FileNotFoundError rather than a zero.
    forms = course["feedback_ids"]
    per_form = {fid: [] for fid in forms}
    per_form[forms[0]] = list(plan["respondents"])

    files = {}
    for fid in forms:
        students = per_form[fid]
        attempts = []
        for n, student in enumerate(students):
            assistant = assistants[plan["group_of"][student] % len(assistants)]
            assistant_q = model.staff_quality(seed, "asistent", assistant)
            items, numeric, rng = model.render_attempt(
                seed, plan, n, student, titular_q, assistant_q
            )
            texts, truth = textbank.generate_texts(rng, items, plan["workload_z"], numeric["part"])

            values = {
                "course": course["shortname"],
                "prof": titular,
                "assist": assistant,
                **items,
                **numeric,
                **texts,
            }
            attempts.append(
                {
                    "id": fid * 100 + n,
                    "courseid": 0,  # anon.json carries 0 here
                    "number": n + 1,
                    "responses": slots.build_responses(fid, values),
                }
            )
            collect["truth"].append(
                {
                    "course_id": course["id"],
                    "feedback_id": fid,
                    "attempt": n,
                    "shortname": course["shortname"],
                    **truth,
                }
            )

        files[fid] = {
            "attempts": [],
            "totalattempts": 0,
            "anonattempts": attempts,
            "totalanonattempts": len(attempts),
            "warnings": [],
        }

    collect["courses"].append(
        {
            "course_id": course["id"],
            "shortname": course["shortname"],
            "level": plan["level"],
            "year": plan["year"],
            "parsed_shortname": plan["parsed"],
            "quality": round(plan["quality"], 3),
            "workload_z": round(plan["workload_z"], 3),
            "enrolled": plan["enrolled"],
            "responses": len(plan["respondents"]),
            "rate": round(plan["rate"], 4),
            "titular": titular,
            "assistants": assistants,
        }
    )
    users = build_users_file(course["id"], titular, assistants, plan["enrolled"])
    return files, users


def write_json(path, payload):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def report(collect):
    courses = collect["courses"]
    if not courses:
        return
    print("\n--- dataset statistics ---")
    print(f"courses: {len(courses)}   attempts: {sum(c['responses'] for c in courses)}")

    unparsed = [c for c in courses if not c["parsed_shortname"]]
    if unparsed:
        print(f"WARNING: {len(unparsed)} shortnames did not parse (level/year defaulted)")

    print("\nresponse rate:")
    for lo in range(0, 30, 5):
        n = sum(1 for c in courses if lo <= c["rate"] * 100 < lo + 5)
        marker = "  <- 7% threshold falls here" if lo == 5 else ""
        print(f"  {lo:2d}-{lo + 5:2d}%  {'#' * min(n, 50):50s} {n:4d}{marker}")

    passing = [c for c in courses if c["rate"] >= 0.07 and c["responses"] >= 3]
    print(f"\ncourses passing   (>=7% and >=3 fb): {len(passing):4d}/{len(courses):<4d}"
          f" -- {len(courses) - len(passing)} filtered")

    resp_by_titular = defaultdict(int)
    resp_by_asistent = defaultdict(int)
    for c in courses:
        resp_by_titular[c["titular"]] += c["responses"]
        for a in c["assistants"]:
            resp_by_asistent[a] += c["responses"] / len(c["assistants"])
    ok_t = sum(1 for v in resp_by_titular.values() if v >= 15)
    ok_a = sum(1 for v in resp_by_asistent.values() if v >= 10)
    print(f"titulari passing  (>=15 fb):         {ok_t:4d}/{len(resp_by_titular):<4d}"
          f" -- {len(resp_by_titular) - ok_t} filtered")
    print(f"asistenti passing (>=10 fb):         {ok_a:4d}/{len(resp_by_asistent):<4d}"
          f" -- {len(resp_by_asistent) - ok_a} filtered")

    qs = sorted(c["quality"] for c in courses)
    print(f"\ncourse quality: min {qs[0]:.2f}  median {qs[len(qs) // 2]:.2f}  max {qs[-1]:.2f}")

    if collect["truth"]:
        filled = sum(1 for t in collect["truth"] if t["fields"])
        print(f"attempts with >=1 free-text answer: {filled}/{len(collect['truth'])}"
              f" ({100 * filled / len(collect['truth']):.0f}%)")


def main():
    cfg = load_config()
    args = parse_arguments(cfg)
    cfg.update(
        min_students=args.min_students,
        max_students=args.max_students,
        min_rate=args.min_response_rate,
        max_rate=args.max_response_rate,
    )
    if args.min_students > args.max_students:
        logger.error("--min-students cannot exceed --max-students")
        return 1
    if args.min_response_rate > args.max_response_rate:
        logger.error("--min-response-rate cannot exceed --max-response-rate")
        return 1

    courses = load_pickle("courses.p")
    feedbacks = load_pickle("feedbacks.p")
    categories = load_pickle("categories.p")
    if not (courses and feedbacks and categories):
        return 1

    selected = select_courses(courses, feedbacks, categories, args.category)
    if not selected:
        logger.error("No courses selected (category=%s). Nothing to do.", args.category)
        return 1
    logger.info(
        "Selected %d courses (%d feedback forms) under category %s",
        len(selected), sum(len(c["feedback_ids"]) for c in selected), args.category or "ALL",
    )

    # Staff assignment uses the FULL list; --limit only trims what we render, so a subset
    # run reproduces the full run's values for the courses it does emit.
    staff, titulari, asistenti = assign_staff(args.seed, selected)
    logger.info("Roster: %d titulari, %d asistenti", len(titulari), len(asistenti))
    if args.limit:
        selected = selected[: args.limit]
        logger.info("Limiting to the first %d courses", len(selected))

    contents_dir = os.path.join(args.out, CONTENTS_DIR)
    users_dir = os.path.join(args.out, USERS_DIR)
    for d in (contents_dir, users_dir):
        if os.path.isdir(d) and os.listdir(d):
            # nothing here deletes files, so a re-run with a different --seed/--category
            # leaves the old ones behind and blends two datasets into one export
            logger.warning("'%s' is not empty -- stale files from a previous run will "
                           "remain alongside the new ones", d)
    os.makedirs(contents_dir, exist_ok=True)
    os.makedirs(users_dir, exist_ok=True)

    collect = {"courses": [], "truth": []}
    n_files = 0
    for course in selected:
        files, users = generate_course(args.seed, course, staff[course["id"]], cfg, collect)
        for fid, payload in files.items():
            write_json(os.path.join(contents_dir, f"{fid}.json"), payload)
            n_files += 1
        write_json(os.path.join(users_dir, f"{course['id']}.json"), users)

    write_json(
        os.path.join(args.out, "manifest.json"),
        {
            "synthetic": True,
            "not_real_data": True,
            "seed": args.seed,
            "category": args.category,
            "courses": len(selected),
            "feedback_files": n_files,
            "note": (
                "Generated by generate-feedback. Scores, staff names and free text are "
                "fabricated. Do not present any ranking built on this data as a statement "
                "about a real course or person."
            ),
        },
    )

    if not args.no_truth:
        truth_dir = os.path.join(args.out, TRUTH_DIR)
        os.makedirs(truth_dir, exist_ok=True)
        for name, rows in (("sentiment", collect["truth"]), ("courses", collect["courses"])):
            path = os.path.join(truth_dir, f"{name}.jsonl")
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info("Wrote %d feedback files and %d users files to '%s'", n_files, len(selected), args.out)
    if args.report:
        report(collect)
    return 0


if __name__ == "__main__":
    sys.exit(main())
