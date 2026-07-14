"""Free-text answers (slots 21-24), generated so they actually carry signal.

The previous generator wrote the literal string "feedback scris" with probability 0.2.
That parses, but it is useless: the four open questions are the only place a reader (or a
sentiment classifier) can learn anything the Likert items don't already say.

Design notes, because they are easy to get wrong:

* Sentiment TRACKS THE SCORES. The tier is derived from the attempt's own continuous item
  values, so a student who rated the course 4.6 writes praise and one who rated it 2.1
  complains. Text and numbers are two views of the same latent opinion.

* ~10% of the time we deliberately draw from an ADJACENT tier. Real people leave nitpicks
  in glowing reviews. Without this, a classifier trained on the result scores ~99% and the
  team learns nothing from building it.

* The nouns are SHARED between the positive and negative banks on purpose. If only the
  negative bank ever said "laboratorul", a naive-Bayes classifier would degenerate into a
  keyword lookup. The discriminating signal lives in the adjectives, verbs and complaint
  clauses -- as it does in real text.

* `difficulty` is not a sentiment question at all. The Moodle wording is "dificultatea
  principală în urmărirea acestei discipline provine din:" -- it asks for a CAUSE. It is
  modelled as a choice among causes, weighted by the student's own worst dimensions, so a
  heavy course really does produce "volum" answers and one with bad slides "materiale".

* Most students write nothing. The fill rate is U-shaped in sentiment: strong opinions, in
  either direction, are far likelier to be written down than indifference.

GRAMMAR. Romanian adjectives, participles and the copula agree with their noun in gender
and number, so a template cannot just concatenate a random noun with a random adjective --
that is how you get "temele e chiar coerent". Every noun below therefore carries an
agreement class, and adjectives/participles are stored already inflected. Mind the neuter:
Romanian neuters take MASCULINE forms in the singular and FEMININE in the plural ("cursul
e util" / "cursurile sunt utile"), which is why `exemplele` and `laboratoarele` are tagged
f.pl.

The banks are written WITH correct diacritics, and a share of the output is then stripped
of them -- which is what real Moodle text looks like. Going the other way (substituting
a->ă, s->ș ... into plain text) does not simulate a student typing with diacritics, it just
corrupts the words: "laboratorul" becomes "lăborățorul".
"""

import math
import unicodedata

from model import MEAN_Q
from slots import ASSIST_ITEMS, COURSE_ITEMS, PROF_ITEMS

# Agreement classes. Neuter singular behaves as m.sg, neuter plural as f.pl.
M, F, FP = "m.sg", "f.sg", "f.pl"

# (text, agreement). Deliberately reused across sentiment tiers.
NOUNS = [
    ("cursul", M),
    ("laboratorul", M),
    ("materialul de curs", M),
    ("proiectul", M),
    ("seminarul", M),
    ("suportul de curs", M),
    ("tematica", F),
    ("partea practică", F),
    ("temele", FP),
    ("exemplele de la curs", FP),
    ("laboratoarele", FP),
]

ADJ_GOOD = {
    "util": {M: "util", F: "utilă", FP: "utile"},
    "interesant": {M: "interesant", F: "interesantă", FP: "interesante"},
    "bine structurat": {M: "bine structurat", F: "bine structurată", FP: "bine structurate"},
    "clar": {M: "clar", F: "clară", FP: "clare"},
    "aplicat": {M: "aplicat", F: "aplicată", FP: "aplicate"},
    "coerent": {M: "coerent", F: "coerentă", FP: "coerente"},
    "bine organizat": {M: "bine organizat", F: "bine organizată", FP: "bine organizate"},
}
ADJ_BAD = {
    "haotic": {M: "haotic", F: "haotică", FP: "haotice"},
    "confuz": {M: "confuz", F: "confuză", FP: "confuze"},
    "plictisitor": {M: "plictisitor", F: "plictisitoare", FP: "plictisitoare"},
    "teoretic": {M: "teoretic", F: "teoretică", FP: "teoretice"},
    "dezorganizat": {M: "dezorganizat", F: "dezorganizată", FP: "dezorganizate"},
    "superficial": {M: "superficial", F: "superficială", FP: "superficiale"},
}
# participles, for "ar trebui {PART}" / "ar putea fi {PART}"
PART_FIX = {
    "actualizat": {M: "actualizat", F: "actualizată", FP: "actualizate"},
    "restructurat": {M: "restructurat", F: "restructurată", FP: "restructurate"},
    "corelat cu laboratorul": {
        M: "corelat cu laboratorul",
        F: "corelată cu laboratorul",
        FP: "corelate cu laboratorul",
    },
    "publicat din timp": {
        M: "publicat din timp",
        F: "publicată din timp",
        FP: "publicate din timp",
    },
    "explicat mai pe îndelete": {
        M: "explicat mai pe îndelete",
        F: "explicată mai pe îndelete",
        FP: "explicate mai pe îndelete",
    },
}
COPULA = {
    M: ["e", "este", "mi s-a părut"],
    F: ["e", "este", "mi s-a părut"],
    FP: ["sunt", "sunt", "mi s-au părut"],
}

# clauses that stand on their own, so they need no agreement
COMPLAINT = [
    "slide-urile sunt incomplete",
    "nu există exemple rezolvate",
    "ritmul e prea alert",
    "laboratorul nu are legătură cu cursul",
    "notarea nu e transparentă",
    "echipamentele din laborator sunt vechi",
    "deadline-urile se suprapun cu alte materii",
    "nu se răspunde pe forum",
]
PRAISE = [
    "se vede că materia e stăpânită",
    "exemplele sunt din practică",
    "se poate aplica în proiecte reale",
    "ritmul e potrivit",
    "laboratoarele completează bine cursul",
    "am înțeles la ce folosește",
]
PERSON = ["profesorul", "titularul", "asistentul", "cadrul didactic"]
PERSON_VP = [
    "explică pe înțeles",
    "e disponibil la întrebări",
    "dă exemple din industrie",
    "corectează rapid temele",
    "răspunde pe forum",
    "are răbdare cu studenții",
]

# {NOUN} {ADJ} {COP} {PART} all agree with the SAME noun, drawn once per template.
BANKS = {
    "positive": {
        "strong_pos": [
            "{NOUN} {COP} chiar {ADJ}; {PRAISE}.",
            "Mi-a plăcut {NOUN} și faptul că {PRAISE}.",
            "{PERSON} {PERSON_VP} și {PERSON_VP}.",
            "Cea mai bună materie din semestru, {PRAISE}.",
            "Foarte {ADJ} {NOUN}. {PERSON} {PERSON_VP}.",
            "{PRAISE}, iar {NOUN} {COP} {ADJ}.",
            "Recomand materia: {PRAISE}.",
        ],
        "pos": [
            "{NOUN} {COP} {ADJ}.",
            "{PERSON} {PERSON_VP}.",
            "În general {PRAISE}.",
            "Mi-a plăcut că {PRAISE}.",
            "{NOUN} {COP} {ADJ} și {PRAISE}.",
            "Partea bună e că {PRAISE}.",
        ],
        "neutral": [
            "{NOUN} {COP} ok.",
            "{NOUN} {COP} {ADJ}, dar {COMPLAINT}.",
            "În general bine, deși {COMPLAINT}.",
            "Nimic deosebit, dar {PRAISE}.",
        ],
        "neg": [
            "Doar {NOUN}, în rest {COMPLAINT}.",
            "Puține. {COMPLAINT}.",
            "Nu prea am ce să laud; {COMPLAINT}.",
        ],
        "strong_neg": [
            "Niciun aspect pozitiv.",
            "Nimic. {COMPLAINT}.",
            "Greu de găsit ceva; {COMPLAINT}.",
        ],
    },
    "negative": {
        "strong_pos": [
            "Nu am ce să reproșez.",
            "Nimic major; poate {NOUN} ar putea fi {PART}.",
            "Aproape nimic.",
        ],
        "pos": [
            "{NOUN} ar putea fi {PART}.",
            "Doar un detaliu: {COMPLAINT}.",
            "Ar ajuta dacă {NOUN} ar fi {PART}.",
        ],
        "neutral": [
            "{NOUN} ar trebui {PART}.",
            "{COMPLAINT}.",
            "{COMPLAINT}. Ar ajuta dacă {NOUN} ar fi {PART}.",
        ],
        "neg": [
            "{NOUN} {COP} prea {ADJ_BAD}, iar {COMPLAINT}.",
            "{COMPLAINT}. Ar ajuta dacă {NOUN} ar fi {PART}.",
            "Nu mi-a plăcut că {COMPLAINT}.",
            "{NOUN} {COP} {ADJ_BAD}; {COMPLAINT}.",
            "{COMPLAINT} și {COMPLAINT}.",
        ],
        "strong_neg": [
            "Totul: {COMPLAINT}, {COMPLAINT}.",
            "{NOUN} {COP} extrem de {ADJ_BAD}. {COMPLAINT}.",
            "Foarte slab. {COMPLAINT} și nimeni nu pare să observe.",
            "{COMPLAINT}. Materia trebuie regândită din temelie.",
        ],
    },
    "other": {
        "strong_pos": ["Felicitări echipei.", "Continuați așa.", "Mulțumesc pentru semestru."],
        "pos": ["Ar merge mai multe exemple.", "Poate mai multe laboratoare aplicate."],
        "neutral": ["-", "nimic", "n/a", "Nu am alte comentarii.", "Sala e prea rece."],
        "neg": ["Orarul de la ora 8 e brutal.", "Prea multe teme în aceeași săptămână."],
        "strong_neg": [
            "Ar trebui schimbat titularul.",
            "Cea mai slabă materie de până acum.",
            "Sper să se schimbe ceva anul viitor.",
        ],
    },
}

# `difficulty` -- cause attribution, not sentiment.
DIFFICULTY_BANK = {
    "volum": [
        "volumul mare de teme raportat la {TIME}",
        "prea multe teme în paralel cu alte discipline",
        "cantitatea de materie față de numărul de credite",
    ],
    "curs": [
        "explicațiile de la curs, care sar peste pași",
        "ritmul alert al cursului",
        "faptul că noțiunile noi nu sunt introduse gradual",
    ],
    "laborator": [
        "faptul că laboratorul presupune lucruri neexplicate",
        "decalajul dintre curs și laborator",
        "timpul insuficient pentru a termina laboratorul",
    ],
    "materiale": [
        "lipsa unor exemple rezolvate în suportul de curs",
        "slide-urile incomplete",
        "lipsa unei bibliografii clare",
    ],
    "prereq": [
        "lipsa cunoștințelor de la {PREREQ}",
        "faptul că se presupun noțiuni de {PREREQ}",
    ],
    "personal": [
        "organizarea mea a timpului",
        "faptul că nu am reușit să țin ritmul",
    ],
    "niciuna": [
        "nu am întâmpinat dificultăți deosebite",
        "nimic anume",
    ],
}
PREREQ = ["analiză matematică", "algebră", "programare", "structuri de date", "fizică"]
TIME = ["timpul disponibil", "numărul de credite", "restul materiilor"]

TIERS = ["strong_neg", "neg", "neutral", "pos", "strong_pos"]

_STANDALONE = {
    "COMPLAINT": COMPLAINT,
    "PRAISE": PRAISE,
    "PERSON": PERSON,
    "PERSON_VP": PERSON_VP,
    "PREREQ": PREREQ,
    "TIME": TIME,
}
_AGREEING = {"ADJ": ADJ_GOOD, "ADJ_BAD": ADJ_BAD, "PART": PART_FIX}


def _tier(z):
    if z < -1.0:
        return "strong_neg"
    if z < -0.25:
        return "neg"
    if z < 0.25:
        return "neutral"
    if z < 1.0:
        return "pos"
    return "strong_pos"


def _strip_diacritics(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _render(rng, template):
    """Fill the placeholders. The noun is drawn ONCE per template, and everything that must
    agree with it -- adjective, participle, copula -- is taken in that noun's form. A slot
    used twice draws distinct values, so we never produce 'cursul și cursul'."""
    noun, agr = rng.choice(NOUNS)
    used = {}
    out, i = [], 0
    while i < len(template):
        ch = template[i]
        if ch != "{":
            out.append(ch)
            i += 1
            continue
        j = template.index("}", i)
        slot = template[i + 1 : j]
        i = j + 1

        if slot == "NOUN":
            out.append(noun)
            continue
        if slot == "COP":
            out.append(rng.choice(COPULA[agr]))
            continue
        if slot in _AGREEING:
            table = _AGREEING[slot]
            pool = [k for k in sorted(table) if k not in used.get(slot, ())] or sorted(table)
            lemma = rng.choice(pool)
            used.setdefault(slot, set()).add(lemma)
            out.append(table[lemma][agr])  # <- the agreement
            continue

        options = _STANDALONE[slot]
        pool = [v for v in options if v not in used.get(slot, ())] or options
        value = rng.choice(pool)
        used.setdefault(slot, set()).add(value)
        out.append(value)
    return "".join(out)


def _surface_noise(rng, text):
    """Real Moodle feedback is mostly typed without diacritics, so strip them from a good
    share of the answers. Never the other way round -- see the module docstring."""
    if not text:
        return text
    if rng.random() < 0.55:
        text = _strip_diacritics(text)
    if rng.random() < 0.20:
        text = text.rstrip(".")
    if rng.random() < 0.10:
        text = text[:1].lower() + text[1:]
    return text


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _fill_probability(field, z, part):
    """U-shaped in sentiment: the indifferent middle writes least. Engaged students (higher
    attendance) write a little more."""
    if field == "positive":
        p = 0.16 + 0.10 * z + 0.06 * z * z
    elif field == "negative":
        p = 0.14 - 0.11 * z + 0.07 * z * z
    elif field == "difficulty":
        p = 0.20 + 0.05 * max(0.0, -z)
    else:  # other
        p = 0.07 + 0.04 * z * z
    p *= 1.0 + 0.12 * (part - 4)
    return _clamp(p, 0.03, 0.70)


def _pick_cause(rng, items, workload_z, sentiment_z):
    """Weighted by the student's own worst dimensions, so the stated cause is consistent
    with the numbers they gave."""
    weights = {
        "volum": math.exp(1.20 * workload_z),
        "curs": math.exp(1.00 * (MEAN_Q - items["prof_teach"])),
        "laborator": math.exp(1.00 * (MEAN_Q - items["assist_teach"])),
        "materiale": math.exp(1.00 * (MEAN_Q - items["lecture_doc"])),
        "prereq": 0.75,
        "personal": 0.85,
        "niciuna": math.exp(1.10 * sentiment_z),
    }
    causes = sorted(weights)
    return rng.choices(causes, weights=[weights[c] for c in causes])[0]


def generate_texts(rng, items, workload_z, part):
    """-> ({slot: text}, truth) for the four free-text slots.

    `truth` is the ground-truth sentiment label, for training/evaluating a classifier
    later. It is returned separately and written to a sidecar -- NEVER into the 25-slot
    response list, which the consumers parse strictly by position.
    """
    scored = [items[k] for k in PROF_ITEMS + ASSIST_ITEMS + COURSE_ITEMS]
    mean = sum(scored) / len(scored)
    z = (mean - MEAN_Q) / 0.62
    tier = _tier(z)

    texts, per_field = {}, {}
    for field in ("positive", "negative", "difficulty", "other"):
        if rng.random() >= _fill_probability(field, z, part):
            texts[field] = ""
            continue

        if field == "difficulty":
            cause = _pick_cause(rng, items, workload_z, z)
            text = _render(rng, rng.choice(DIFFICULTY_BANK[cause]))
            per_field[field] = {"cause": cause}
        else:
            # ~10% label noise: draw from an adjacent tier. Keeps the corpus learnable but
            # not memorisable.
            drawn = tier
            if rng.random() < 0.10:
                idx = _clamp(TIERS.index(tier) + rng.choice((-1, 1)), 0, len(TIERS) - 1)
                drawn = TIERS[idx]
            text = _render(rng, rng.choice(BANKS[field][drawn]))
            per_field[field] = {"tier": drawn, "tier_noised": drawn != tier}

        texts[field] = _surface_noise(rng, text)

    truth = {"sentiment_z": round(z, 3), "tier": tier, "fields": per_field}
    return texts, truth
