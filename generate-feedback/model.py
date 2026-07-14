"""The latent-quality model: what makes the generated numbers mean something.

The previous generator drew every Likert item independently and uniformly. That produces
well-formed files in which every course and every teacher converges to a mean of ~3.0.
The whole point of the downstream pipeline is to DISCRIMINATE -- it ranks courses and
teachers and applies selection thresholds (course >=7% response rate & >=3 responses;
titular >=7% & >=15 responses; asistent >=10 responses). Under uniform noise the rankings
are arbitrary, the score histogram is flat, and the thresholds filter nothing. The demo
renders and says nothing.

So: every course, titular and asistent gets a hidden quality. Each answer is a noisy
function of the relevant hidden quality, plus a per-student bias. That gives the ranking
pages something real to find, and makes the thresholds bite.

All internal maths happens on the 5-is-best scale that the consumers see AFTER their
`6 - raw` decode, so every coefficient below is readable as "stars". Conversion to
Moodle's inverted 1-is-best index happens exactly once, in slots.encode_likert.

Standard library only -- the repo has no dependencies and keeps it that way.
"""

import hashlib
import math
import random
import re

from slots import ASSIST_ITEMS, COURSE_ITEMS, PROF_ITEMS

# Where the population sits. Real course evaluations skew positive: most means land
# between 3.5 and 4.5 of 5, with a thin left tail. A symmetric distribution centred on 3
# would be the giveaway that the data is fake.
MEAN_Q = 3.83
LATENT_LO, LATENT_HI = 1.5, 4.8  # capped short of 5.0: a saturated ceiling turns the
# Top-10 into an arbitrary tiebreak among perfect scores.

# Per-item offsets (in stars). These give the item-level bar chart a believable profile:
# staff always score highest on knowledge and politeness, lowest on documentation.
ITEM_OFFSET = {
    "prof_know": +0.40,
    "prof_teach": -0.05,
    "prof_interact": -0.20,
    "prof_behave": +0.30,
    "lecture_doc": -0.30,
    "assist_know": +0.25,
    "assist_teach": -0.10,
    "assist_interact": -0.05,
    "assist_behave": +0.30,
    "lab_doc": -0.35,
    "assign_useful": -0.10,
}

ITEM_SIGMA = 0.55  # per-answer noise. Tuned so items within a block correlate at
# r ~= 0.6 -- real, not the r ~= 0.98 a noiseless model would give.

# Typical enrolment by (level, year). A first-year mandatory course has hundreds of
# students; a master elective has ~25. This is what makes the response-RATE threshold
# (7%) behave differently from the response-COUNT threshold (3 / 15 / 10).
BASE_ENROLLED = {
    ("L", 1): 220, ("L", 2): 195, ("L", 3): 155, ("L", 4): 120,
    ("M", 1): 35, ("M", 2): 26,
}

_RE_LEVEL = re.compile(r"-(L|M)-")
_RE_YEAR = re.compile(r"-A(\d)-")


def derive(seed, *parts):
    """A random.Random keyed on (seed, *parts).

    Uses blake2b, never the builtin hash(): hash() is salted per process by
    PYTHONHASHSEED, which would make output non-reproducible across runs.

    Because per-course draws are keyed on the course id (not on iteration order), a
    --limit run produces byte-identical files for the courses it does emit.
    """
    key = "|".join([str(seed), *(str(p) for p in parts)]).encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=16).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _latent(rng, a, b):
    """Left-skewed quality on [LATENT_LO, LATENT_HI] via a Beta draw."""
    return LATENT_LO + (LATENT_HI - LATENT_LO) * rng.betavariate(a, b)


def parse_shortname(shortname):
    """'03-ACS-L-CTI-Calculatoare-A1-S2-XXX-CD' -> ('L', 1). Falls back to ('L', 2) and
    reports it, so a parse failure can't quietly make every course identical (which is
    exactly how the previous generator's bugs stayed invisible)."""
    level = _RE_LEVEL.search(shortname)
    year = _RE_YEAR.search(shortname)
    if not level or not year:
        return "L", 2, False
    lvl = level.group(1)
    yr = int(year.group(1))
    if (lvl, yr) not in BASE_ENROLLED:
        return lvl, (1 if lvl == "M" else 2), False
    return lvl, yr, True


def staff_quality(seed, kind, staff_id):
    rng = derive(seed, kind, staff_id)
    # Assistants are more junior: slightly lower mean, wider spread.
    return _latent(rng, 5.0, 2.0) if kind == "titular" else _latent(rng, 4.2, 2.0)


def course_plan(seed, course_id, shortname, titular_q, assistant_qs, cfg):
    """Everything about a course that does not depend on the individual student."""
    rng = derive(seed, "course", course_id)
    level, year, parsed = parse_shortname(shortname)

    intrinsic = _latent(rng, 5.0, 2.0)  # the syllabus/content itself
    workload_z = _clamp(rng.normalvariate(0, 1), -2.5, 2.5)  # orthogonal to quality!

    # A course is partly its content and partly the people teaching it.
    mean_assist = sum(assistant_qs) / len(assistant_qs) if assistant_qs else MEAN_Q
    quality = _clamp(
        0.55 * intrinsic + 0.30 * titular_q + 0.15 * mean_assist + rng.normalvariate(0, 0.20),
        1.4,
        4.85,
    )

    # Equipment is a property of the ROOM, shared by the courses of a (level, year), not
    # of the teacher. Modelling it as quality-driven is what produces the fake-perfect
    # course that is also excellent, easy and beautifully equipped.
    equipment_q = derive(seed, "equip", level, year).normalvariate(3.35, 0.55)

    # Enrolment is driven by the course's level and year -- a first-year mandatory course
    # really does have ten times the students of a master elective, and that spread is what
    # makes the response-RATE threshold (7%) behave differently from the response-COUNT
    # thresholds (3 / 15 / 10). min/max_students are absolute bounds on the result, not the
    # range itself; their defaults are deliberately wide enough not to flatten that spread.
    base = BASE_ENROLLED[(level, year)]
    enrolled = _clamp(
        round(base * rng.lognormvariate(0, 0.22)), cfg["min_students"], cfg["max_students"]
    )

    # Response rate: right-skewed, centred near 11%, straddling the 7% threshold. Bigger
    # courses answer less; slightly better courses answer slightly more (a real and
    # DELIBERATE non-response bias -- see README, it must not be reported as a finding).
    size_mult = 1.45 if enrolled <= 40 else 1.15 if enrolled <= 100 else 0.95 if enrolled <= 180 else 0.80
    rate = _clamp(
        (cfg["min_rate"] + (cfg["max_rate"] - cfg["min_rate"]) * rng.betavariate(2.2, 5.0))
        * size_mult
        * (1 + 0.08 * (quality - MEAN_Q)),
        0.0,
        0.55,
    )
    # Floor of 1: rounding can otherwise land a small course on zero respondents, and a
    # feedback file with no attempts carries no information while still being globbed.
    n_resp = _clamp(round(enrolled * rate), 1, enrolled)

    # Lab groups: students split across the assistants, so each assistant accumulates a
    # different number of responses -- some clear the >=10 bar, some don't.
    n_groups = max(1, len(assistant_qs))
    group_of = [i % n_groups for i in range(enrolled)]
    rng.shuffle(group_of)
    respondents = sorted(rng.sample(range(enrolled), n_resp))

    return {
        "course_id": course_id,
        "shortname": shortname,
        "level": level,
        "year": year,
        "parsed": parsed,
        "quality": quality,
        "workload_z": workload_z,
        "equipment_q": equipment_q,
        "enrolled": enrolled,
        "rate": rate,
        "respondents": respondents,
        "group_of": group_of,
    }


def render_attempt(seed, plan, index, student, titular_q, assistant_q):
    """One student's 15 Likert items + 3 numerics, on the 5-is-best scale."""
    rng = derive(seed, "attempt", plan["course_id"], student)

    ability = rng.normalvariate(0, 1)
    engage = 0.45 * ability + rng.normalvariate(0, 0.85)
    leniency = rng.normalvariate(0, 0.42) + 0.18 * engage  # grumpy vs generous rater;
    # shared across all 15 items, which is what produces the global positivity bias
    b_course = rng.normalvariate(0, 0.30)
    b_prof = rng.normalvariate(0, 0.38)  # this student's take on the lecturer, shared by
    b_assist = rng.normalvariate(0, 0.38)  # all 5 items of the block -> within-block corr

    items = {}
    for key in PROF_ITEMS:
        items[key] = titular_q + b_prof + leniency + ITEM_OFFSET[key] + rng.normalvariate(0, ITEM_SIGMA)
    for key in ASSIST_ITEMS:
        items[key] = assistant_q + b_assist + leniency + ITEM_OFFSET[key] + rng.normalvariate(0, ITEM_SIGMA)

    q, w = plan["quality"], plan["workload_z"]
    items["assign_useful"] = (
        q + b_course + leniency + ITEM_OFFSET["assign_useful"] + rng.normalvariate(0, ITEM_SIGMA)
    )

    # `load` and `assign_diff` are NOT quality-driven. The Moodle wording makes agreement
    # mean "workload is lower than other courses" / "the amount of work was appropriate",
    # and an excellent course is very often a HEAVY one. Driving these from quality would
    # manufacture the course that is simultaneously brilliant and effortless -- the single
    # most obvious tell of synthetic data.
    items["load"] = 3.25 - 0.80 * w + 0.15 * (q - MEAN_Q) + 0.6 * leniency + rng.normalvariate(0, 0.60)
    items["assign_diff"] = 3.20 - 0.70 * w + 0.10 * (q - MEAN_Q) + 0.6 * leniency + rng.normalvariate(0, 0.60)
    items["equipment"] = (
        plan["equipment_q"] + 0.10 * (q - MEAN_Q) + 0.6 * leniency + rng.normalvariate(0, 0.55)
    )

    # Halo: the overall verdict is computed LAST, from the block means this student
    # actually gave -- so it is coupled to them the way it is in real data.
    prof_mean = sum(items[k] for k in PROF_ITEMS) / len(PROF_ITEMS)
    assist_mean = sum(items[k] for k in ASSIST_ITEMS) / len(ASSIST_ITEMS)
    items["eval_overall"] = (
        0.45 * q
        + 0.35 * prof_mean
        + 0.20 * assist_mean
        + b_course
        + 0.5 * leniency
        + rng.normalvariate(0, 0.40)
    )

    grade = 7.55 + 0.50 * (q - MEAN_Q) + 0.95 * ability + 0.45 * engage + rng.normalvariate(0, 0.75)
    part = 3 if engage < -0.55 else 4 if engage < 0.45 else 5

    hours = rng.lognormvariate(0.75 + 0.40 * w + 0.10 * engage, 0.45)
    if rng.random() < 0.02:
        hours *= rng.uniform(2.0, 3.2)  # real free-numeric fields always have absurd outliers

    numeric = {
        "expected_grade": _clamp(round(grade), 5, 10),
        "part": part,
        "assign_time": _clamp(round(hours), 1, 25),
    }
    return items, numeric, rng


def block_means(items):
    return {
        "course": sum(items[k] for k in COURSE_ITEMS) / len(COURSE_ITEMS),
        "prof": sum(items[k] for k in PROF_ITEMS) / len(PROF_ITEMS),
        "assist": sum(items[k] for k in ASSIST_ITEMS) / len(ASSIST_ITEMS),
    }
