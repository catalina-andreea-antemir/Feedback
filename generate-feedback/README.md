# Feedback Generator

Generates a synthetic feedback dataset in the exact shape a real Moodle export has, so the
processing pipeline and the web interface can be developed and demoed without touching real
student data.

**The data is fabricated.** Scores, staff names and free-text answers are all generated. Never
present a ranking built on this dataset as a statement about a real course or a real person.
Every run writes a `manifest.json` marking the export synthetic; keep that flag visible in
whatever consumes it.

## Running

```bash
python3 convert_script.py                     # jsons/ -> pickles/
python3 main.py --seed 1 --report             # -> out/
python3 validate.py --out out                 # proves the output is consumable
```

Standard library only — there is nothing to install.

Useful flags:

| Flag | Meaning |
|------|---------|
| `--seed N` | Same seed ⇒ byte-identical output. `--limit` reproduces the same values a full run gives those courses. |
| `--category N` | Only courses under Moodle category `N`. Default **7 (ACS)**. `0` = the whole platform (~9700 forms, several GB). |
| `--limit N` | Only the first N courses. For smoke tests. |
| `--min-students` / `--max-students` | Absolute bounds on **enrolled** students per course (see below). |
| `--min-response-rate` / `--max-response-rate` | Fraction of enrolled students who answer. |
| `--report` | Print dataset statistics after generating. |
| `--no-truth` | Skip the ground-truth sidecar. |

### Breaking change to the existing flags

`MIN_STUDENTS` / `MAX_STUDENTS` (and `--min-students` / `--max-students`) now mean **enrolled
students**, not the number of responses. The response count is derived from enrolment via a
per-course response rate. This is what makes the completion percentage (`responses / enrolled`)
meaningful and keeps it at or under 100% — previously there was no enrolment at all, so it
could not be computed.

They are absolute *bounds*, not the range itself: enrolment follows the course's level and year
(`model.BASE_ENROLLED` — a first-year mandatory course carries ~220 students, a master elective
~26). The defaults are deliberately wide. Narrowing them squashes large and small courses to the
same size, and that size spread is exactly what makes the 7% response-*rate* threshold bite
differently from the response-*count* thresholds.

## Output

```
out/
  feedback_contents/<feedback_id>.json   the 25-slot attempts
  users/<course_id>.json                 enrolled users (students + titular + asistenti)
  groundtruth/sentiment.jsonl            true sentiment label per free-text answer
  groundtruth/courses.jsonl              the hidden per-course quality/workload latents
  manifest.json                          seed, scope, "synthetic": true
```

`feedback_contents/` and `users/` are the two directories the consumers read. The web interface
ignores the export entirely unless **both** are present, next to the pickles. Their names are not
configurable — the consumers hardcode them.

A course can own several feedback forms, and the two consumers disagree about what that means:
the web interface **merges** the attempts of every form, while `processor.feedback4course` picks
the single **fullest** form and ignores the others. So all of a course's respondents go on one
form, and its sibling forms are written as empty files — `processor.num_entries_in_feedback`
opens each form of a course without checking it exists, so an absent file would be a crash rather
than a zero. That way both consumers report the same number of responses for the same course.

`groundtruth/` is deliberately outside them: the consumers parse the response list strictly by
position and reject anything unexpected, so the labels cannot live in-band. They exist so a
sentiment classifier can be trained and evaluated on the free-text answers without a manual
labelling pass.

## The 25-slot contract

A feedback attempt is **exactly 25 responses, read by position** — never by question text (the
titular and asistent blocks reuse identical wording, so the text is not a key). `slots.py` is
the single source of truth; `anon.json` is a real anonymized dump that shows the same shape.

| # | key | kind | | # | key | kind |
|---|-----|------|-|---|-----|------|
| 0 | course | course **shortname** | | 13 | assist_know | likert |
| 1 | prof | titular name | | 14 | assist_teach | likert |
| 2 | assist | asistent name | | 15 | assist_interact | likert |
| 3 | eval_overall | likert | | 16 | assist_behave | likert |
| 4 | expected_grade | int 5..10 | | 17 | lab_doc | likert |
| 5 | load | likert | | 18 | assign_time | int ≥ 1 |
| 6 | equipment | likert | | 19 | assign_diff | likert |
| 7 | part | int, raw 3/4/5 | | 20 | assign_useful | likert |
| 8 | prof_know | likert | | 21 | positive | free text |
| 9 | prof_teach | likert | | 22 | negative | free text |
| 10 | prof_interact | likert | | 23 | difficulty | free text |
| 11 | prof_behave | likert | | 24 | other | free text |
| 12 | lecture_doc | likert | | | | |

Three rules that are easy to get wrong:

1. **Likert `rawval` is the Moodle option index, where `1` is the BEST answer.** Consumers
   decode it with `6 - int(raw)` to reach a 5-is-best score. Only ever emit `"1"`..`"5"`. Real
   exports do contain `"0"` for an unanswered item, but the consumers disagree about what it
   means, so we never produce it. Same reason `assign_time` is floored at 1.
2. **`printval` must equal `rawval`** on the identity and free-text slots (0, 1, 2, 21–24). One
   consumer reads those from `rawval`, the other from `printval`.
3. **`part`, `expected_grade` and `assign_time` are not reverse-coded.** They are plain integers.
   Do not "fix" them to match the Likert items.

## Why the numbers look the way they do

Drawing every answer uniformly at random produces well-formed files in which every course and
every teacher converges to a mean of ~3.0. The pipeline exists to *discriminate* — it ranks
courses and teachers and applies selection thresholds (course ≥7% response rate & ≥3 responses;
titular ≥7% & ≥15 responses; asistent ≥10 responses). Under uniform noise the rankings are
arbitrary, the score histogram is flat, and the thresholds filter nothing.

So every course, titular and asistent carries a hidden quality, and each answer is a noisy
function of the relevant one, plus a per-student bias (see `model.py`). Consequences worth
knowing about:

- Ratings skew positive, as real course evaluations do: most course means land between 3.5 and
  4.5 of 5, with a thin left tail.
- Items within a block correlate — a student who rates the lecturer highly rates all five
  lecturer questions highly — and `eval_overall` is coupled to the block means (a halo effect).
- `load`, `assign_diff` and `equipment` are deliberately **not** driven by course quality. An
  excellent course is very often a heavy one, and equipment belongs to the room, not the
  teacher. Modelling these as quality-driven manufactures the course that is simultaneously
  brilliant, effortless and beautifully equipped — the clearest tell of synthetic data.
- Free-text sentiment tracks the scores, with ~10% deliberately drawn from an adjacent
  sentiment tier (real people leave nitpicks in glowing reviews). The nouns are shared between
  the positive and negative banks on purpose: otherwise a classifier just learns keywords.
- `difficulty` is a cause-attribution question, not a sentiment one, so it is modelled as a
  choice among causes weighted by the student's own worst answers.

### These correlations are designed in, not findings

Response rate is coupled to course quality; workload drives `assign_time`; attendance is coupled
to expected grade. They will look like insights. They are artefacts of the generator. Anything
built on this data should say so.

## Files

| File | Role |
|------|------|
| `slots.py` | The 25-slot contract and the encoders. Import it rather than re-deriving the order. |
| `model.py` | Hidden qualities, response rates, enrolment; the deterministic RNG. |
| `textbank.py` | Romanian free-text templates, correlated with the scores. |
| `names.py` | Fictional staff roster. |
| `main.py` | Orchestration and CLI. |
| `validate.py` | Re-implements both consumers' acceptance rules. Run it after generating. |
| `convert_script.py` | `jsons/` → `pickles/`. |
| `anon.json` | A real anonymized attempt — the reference for the format. |
