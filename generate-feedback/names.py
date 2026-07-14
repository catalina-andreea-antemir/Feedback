"""Fictional teaching staff.

The names below are common Romanian given/family names combined at random. They are
deliberately generic and are NOT drawn from any real faculty roster -- but a collision
with a real person is still possible by chance, which is why every consumer of this data
must keep its "synthetic data" banner visible. Never present a ranking built on this
data as a statement about a real person.

Why the roster matters at all: the consumers group teaching staff by the NAME STRING
found in the `prof` / `assist` slots. The previous generator wrote "Prenume NUME" for
every teacher of every course, which collapsed the whole faculty onto one person and made
the Top-10 titulari / asistenti pages meaningless. Names must therefore be distinct, and
stable per course.
"""

import unicodedata

GIVEN = [
    "Andrei", "Mihai", "Cristian", "Alexandru", "Radu", "Bogdan", "Vlad", "Stefan",
    "Cosmin", "Razvan", "Adrian", "Sorin", "Dragos", "Tudor", "Marius", "Iulian",
    "Octavian", "Silviu", "Cristina", "Ioana", "Elena", "Andreea", "Maria", "Diana",
    "Alina", "Roxana", "Gabriela", "Simona", "Anca", "Laura", "Irina", "Raluca",
    "Corina", "Mihaela", "Carmen", "Oana", "Daniela", "Monica",
]

FAMILY = [
    "POPESCU", "IONESCU", "DUMITRU", "GEORGESCU", "STANCIU", "MARIN", "DIACONU",
    "BARBU", "NEAGU", "TUDORACHE", "VOICU", "PETRESCU", "SANDU", "CIOBANU", "ANGHEL",
    "MOCANU", "OPREA", "NICOLAE", "ILIE", "FLOREA", "DOBRE", "SERBAN", "RUSU",
    "MATEI", "COSTIN", "ENACHE", "LAZAR", "TOMA", "PARASCHIV", "BADEA", "CROITORU",
    "MIHALACHE", "TANASE", "VLAD", "NITU", "GRIGORE", "ZAHARIA", "CALIN", "PANAIT",
    "IORDACHE", "SAVU", "TRANDAFIR", "MUNTEANU", "CAZACU", "DINU", "BUCUR",
]


def _ascii(text):
    """Moodle exports carry diacritics inconsistently; keep staff names plain ASCII so a
    name is one stable grouping key everywhere it appears."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def build_roster(rng, count):
    """`count` distinct fullnames. Deduplicated: a repeated name would silently merge two
    people in every consumer's group-by.

    'Given FAMILY' gives len(GIVEN) * len(FAMILY) combinations, which covers one faculty
    but not the whole platform: `--category 0` needs ~8600 staff. Rather than pad the
    banks with thousands of names, exhaust the simple pool first and then fall back to
    double-barrelled surnames ('Andrei POPESCU-IONESCU') -- ordinary in Romanian, and it
    raises the ceiling to len(GIVEN) * len(FAMILY) * (len(FAMILY) - 1).
    """
    capacity = len(GIVEN) * len(FAMILY) * (len(FAMILY) - 1)
    if count > capacity:
        raise ValueError(f"cannot draw {count} distinct names from {capacity} combinations")

    seen, roster = set(), []
    simple_capacity = len(GIVEN) * len(FAMILY)
    while len(roster) < count:
        given = rng.choice(GIVEN)
        family = rng.choice(FAMILY)
        if len(roster) >= simple_capacity * 3 // 4:
            # the simple pool is close to exhausted; rejection sampling would start to
            # spin, so switch to the wider space
            second = rng.choice([f for f in FAMILY if f != family])
            family = f"{family}-{second}"
        name = _ascii(f"{given} {family}")
        if name not in seen:
            seen.add(name)
            roster.append(name)
    return roster
