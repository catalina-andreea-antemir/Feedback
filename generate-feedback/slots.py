"""The 25-slot response contract -- the single source of truth for the output format.

A Moodle feedback attempt is a list of exactly 25 responses, read BY POSITION. The
consumers never match on the question text (they can't: the titular and asistent blocks
reuse identical wording -- see slots 11/16 and 12/17 below). The slot order here is the
same one hardcoded in:

    process-feedback/processor.py   FeedbackContent.keys
    web-interface/taxonomy.py       _RESPONSE_SLOTS

and it is what `anon.json` (a real anonymized Moodle dump) actually contains.

Three encoding rules the consumers depend on, all enforced here so a caller cannot get
them wrong:

1. Likert `rawval` is the Moodle option index, where **1 = best**. Consumers decode it
   with `6 - int(raw)` to reach a 5-is-best score. `rawval` must always be "1".."5" --
   never "0". Real Moodle exports DO contain "0" for an unanswered item, but the two
   consumers disagree about it (processor.py drops it; taxonomy._likert("0") returns 6,
   which is off-scale), so we never emit it. Same reason `assign_time` is floored at 1.

2. `printval == rawval` for the identity and free-text slots (0, 1, 2, 21-24).
   processor.py reads those from `rawval`; taxonomy.py reads them from `printval`.
   anon.json satisfies both only because the two fields are identical there.

3. `part`, `expected_grade` and `assign_time` are NOT reverse-coded -- they are plain
   integers. Encoding dispatches on `kind`, so they can never be run through the `6 - x`
   inversion by accident.
"""

LIKERT = "likert"
RAW_INT = "raw_int"
IDENTITY = "identity"
TEXT = "text"

# (key, moodle question name, kind). The `name` strings are byte-identical to anon.json;
# they are truncated in the real export and we keep them that way.
SLOTS = (
    ("course", "Subject", IDENTITY),
    ("prof", "Teacher", IDENTITY),
    ("assist", "Laboratory/seminar/project ...", IDENTITY),
    ("eval_overall", "Is your assessment of this ...", LIKERT),
    ("expected_grade", "What grade do you expect to...", RAW_INT),
    ("load", "Is the general workload in ...", LIKERT),
    ("equipment", "Location / hardware and ...", LIKERT),
    ("part", "The approximate number of ...", RAW_INT),
    ("prof_know", "Does the course tutor have ...", LIKERT),
    ("prof_teach", "Was the teaching method ...", LIKERT),
    ("prof_interact", "Did the course stimulate ...", LIKERT),
    ("prof_behave", "Was the behavior of the ...", LIKERT),  # same name as assist_behave
    ("lecture_doc", "Are the teaching materials ...", LIKERT),  # same name as lab_doc
    ("assist_know", "Does the laboratory teacher...", LIKERT),
    ("assist_teach", "Did the laboratory teacher ...", LIKERT),
    ("assist_interact", "Did the applications ...", LIKERT),
    ("assist_behave", "Was the behavior of the ...", LIKERT),
    ("lab_doc", "Are the teaching materials ...", LIKERT),
    ("assign_time", "Estimate the average number...", RAW_INT),
    ("assign_diff", "Were the amount and ...", LIKERT),
    ("assign_useful", "Did the topics / projects /...", LIKERT),
    ("positive", "What are the positive ...", TEXT),
    ("negative", "What do you think needs to ...", TEXT),
    ("difficulty", "In your opinion, the main ...", TEXT),
    ("other", "Other personal comments or ...", TEXT),
)

# The bug this whole module exists to prevent: the previous generator emitted 12.
assert len(SLOTS) == 25, "the consumers hard-reject any attempt that isn't exactly 25 responses"

KEYS = [k for k, _name, _kind in SLOTS]

# Slots whose printval must equal their rawval (rule 2 above).
MIRRORED = frozenset(k for k, _n, kind in SLOTS if kind in (IDENTITY, TEXT))

# Blocks of Likert items driven by a common latent (see model.py).
COURSE_ITEMS = ("eval_overall", "load", "equipment", "assign_diff", "assign_useful")
PROF_ITEMS = ("prof_know", "prof_teach", "prof_interact", "prof_behave", "lecture_doc")
ASSIST_ITEMS = ("assist_know", "assist_teach", "assist_interact", "assist_behave", "lab_doc")

# rawval -> printval, exactly as Moodle renders it. raw 1 is the BEST option.
LIKERT_PRINT = {
    "1": "5  - Complet de Acord",
    "2": "4  - ...",
    "3": "3  - ...",
    "4": "2  - ...",
    "5": "1  - Deloc de acord",
}

# `part` (attendance) is a plain numeric slot: a HIGHER raw means MORE attendance.
# It is not reverse-coded -- do not "fix" this to match the Likert items.
PART_PRINT = {
    "3": "40% .. 60%",
    "4": "60% .. 80%",
    "5": "80% .. 100%",
}


def _clamp(value, low, high):
    return max(low, min(high, value))


def encode_likert(score):
    """5-is-best score -> (printval, rawval). The clamp to 1..5 is the ONLY thing keeping
    rawval out of "0" territory, so every Likert value must pass through here."""
    score = _clamp(int(round(score)), 1, 5)
    raw = str(6 - score)
    return LIKERT_PRINT[raw], raw


def encode_part(raw):
    raw = str(_clamp(int(raw), 3, 5))
    return PART_PRINT[raw], raw


def encode_grade(grade):
    raw = str(_clamp(int(round(grade)), 5, 10))
    return raw, raw


def encode_hours(hours):
    """Weekly hours on assignments. Floored at 1: processor.convert_value keeps 0 but
    add_response then drops falsy values, so a 0 would silently vanish from the mean."""
    raw = str(_clamp(int(round(hours)), 1, 25))
    return raw, raw


def encode_text(value):
    value = value or ""
    return value, value


def encode_identity(value):
    return value, value


def response_ids(feedback_id):
    """The 25 Moodle question-item ids for a feedback form. In anon.json these are
    identical across every attempt of a form (they identify the question, not the
    answer), so we build them once per form and reuse them."""
    base = feedback_id * 100
    return [base + i for i in range(len(SLOTS))]


def build_responses(feedback_id, values):
    """values: {slot_key: raw python value} -> the 25-element `responses` list."""
    ids = response_ids(feedback_id)
    out = []
    for (key, name, kind), rid in zip(SLOTS, ids):
        value = values[key]
        if kind is LIKERT:
            printval, rawval = encode_likert(value)
        elif kind is IDENTITY:
            printval, rawval = encode_identity(value)
        elif kind is TEXT:
            printval, rawval = encode_text(value)
        elif key == "part":
            printval, rawval = encode_part(value)
        elif key == "expected_grade":
            printval, rawval = encode_grade(value)
        elif key == "assign_time":
            printval, rawval = encode_hours(value)
        else:
            raise AssertionError(f"unhandled slot {key}")
        out.append({"id": rid, "name": name, "printval": printval, "rawval": rawval})
    assert len(out) == 25
    return out
