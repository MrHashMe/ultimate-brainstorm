"""Deterministic family seat assignment (KIT_SPEC 6.6). Stored in run.json `seats`.

F = available and privacy-allowed families, host first, then the configured order. With one family every "other"
seat becomes `<host>-alt` (PROVISIONAL). All choices are deterministic; archetypes use rng(run, "arch").
"""

import hashlib
import random

from . import FAMILY_ORDER, VENDORS, base_family

ARCH_K = {"quick": 2, "standard": 3, "proposal": 3, "deep": 4}
RUBRIC_N = {"quick": 1, "standard": 2, "proposal": 2}


def rng(run_name, tag):
    """Same seeding as bs.py: random.Random(sha256('<run folder name>|<tag>'))."""
    return random.Random(hashlib.sha256(("%s|%s" % (run_name, tag)).encode("utf-8")).hexdigest())


def family_list(host, available, allowed_vendors=None, order=FAMILY_ORDER):
    """F: available and allowed, host first, then `order`."""
    avail = [f for f in available]
    allowed = set(allowed_vendors or [])

    def ok(f):
        return (not allowed) or VENDORS.get(f, f) in allowed

    out = []
    if host in avail and ok(host):
        out.append(host)
    for f in list(order) + [f for f in avail if f not in order]:
        if f in avail and f not in out and ok(f):
            out.append(f)
    return out


def assign(run_name, host, F, web, mode="standard", variant="general", s1_engine="s1f"):
    """Return the seats dict for run.json.

    host: the host family (always seated, even if its CLI is unavailable, since the host itself answers HOST work).
    F: the ordered family list (host first when available). web: {family: bool} after privacy.
    """
    fams = list(F) or [host]
    if fams[0] != host:
        fams = [host] + [f for f in fams if f != host]
    others = [f for f in fams if f != host]
    alt = "%s-alt" % host
    single = not others
    counter = {"n": 0}

    def other_rr():
        if not others:
            return alt
        f = others[counter["n"] % len(others)]
        counter["n"] += 1
        return f

    def is_web(f):
        return bool(web.get(base_family(f)))

    web_fams = [f for f in fams if is_web(f)]
    s4 = host if is_web(host) else (web_fams[0] if web_fams else host)

    gens = {"S1": host, "S2": host, "S4": s4}
    gens["S3"] = other_rr()
    gens["S5"] = other_rr()
    if mode == "deep":
        for i in range(1, 7):
            gens["L%d" % i] = other_rr()
    # GAP and REOPEN continue the same round-robin at dispatch time (see gap_family / reopen_families).
    rr_next = counter["n"]

    researcher = [host] if is_web(host) else ([web_fams[0]] if web_fams else [host])
    if mode == "deep":
        second = [f for f in (web_fams + fams) if f != researcher[0]]
        researcher.append(second[0] if second else alt)

    checker_pool = web_fams[:] if web_fams else [host]

    def judges(kind_mode):
        if kind_mode == "quick":
            return [others[0] if others else alt]
        if kind_mode == "deep":
            js = fams[:4]
            return js if len(js) > 1 else [host, alt]
        js = [host] + others[:2]
        return js if len(js) > 1 else [host, alt]

    screen_judges = judges(mode)
    tournament_judges = judges(mode)

    redteam_rotation = fams[:] if len(fams) > 1 else [host, alt]

    k = ARCH_K.get(mode, 3)
    author_order = others + [host]
    arch_authors = [author_order[i % len(author_order)] for i in range(k)]
    authored = set(arch_authors)
    non_authors = [f for f in fams if f not in authored]
    if non_authors:
        arch_judges = non_authors + ([host] if host not in non_authors else [])
    else:
        arch_judges = fams[:]
    if mode == "quick":
        arch_judges = arch_judges[:1]
    if len(arch_judges) == 0:
        arch_judges = [alt]

    letters = ["A", "C"] if mode == "quick" else (["A", "B", "C", "D"] if mode == "deep" else ["A", "B", "C"])
    letters = letters[:k]
    shuffled = letters[:]
    rng(run_name, "arch").shuffle(shuffled)
    archetypes = dict(("%d" % (i + 1), shuffled[i]) for i in range(len(arch_authors)))
    same_family = len(set(arch_authors)) < len(arch_authors)

    if mode == "deep":
        rubric = others[:] or [alt]
    else:
        rubric = (others[:RUBRIC_N.get(mode, 2)]) or [alt]
    proposal = {"drafter": host, "rubric": rubric, "redteam": others[-1] if others else alt}

    return {
        "s1_engine": s1_engine,
        "host": host,
        "families": fams,
        "others": others,
        "single_family": single,
        "generators": gens,
        "rr_next": rr_next,
        "researcher": researcher,
        "checker_pool": checker_pool,
        "screen_judges": screen_judges,
        "tournament_judges": tournament_judges,
        "redteam_rotation": redteam_rotation,
        "arch_authors": arch_authors,
        "arch_archetypes": archetypes,
        "arch_same_family": same_family,
        "arch_judges": arch_judges,
        "arch_writer": None,
        "proposal": proposal,
        "web_families": web_fams,
    }


def rr_family(seats, index):
    """The index-th family of the non-host round-robin continued after the generator seats (GAP, REOPEN)."""
    others = seats.get("others") or []
    if not others:
        return "%s-alt" % seats.get("host", "claude")
    return others[(int(seats.get("rr_next", 0)) + index) % len(others)]


def gap_families(seats, n):
    return [rr_family(seats, i) for i in range(n)]


def reopen_families(seats, mode):
    n = 2 if mode == "deep" else 1
    others = seats.get("others") or []
    if not others:
        return ["%s-alt" % seats.get("host", "claude")] * n
    return [others[i % len(others)] for i in range(n)]


def checker_for(seats, origin_vendor):
    """A web-capable family whose vendor differs from the idea's origin vendor, preferring the host."""
    pool = seats.get("checker_pool") or [seats.get("host", "claude")]
    for f in pool:
        if VENDORS.get(base_family(f), f) != origin_vendor:
            return f, False
    return pool[0], True


def redteam_pair(seats, index):
    """(advocate, critic) for the index-th idea: always different families; the advocate rotates."""
    rot = seats.get("redteam_rotation") or [seats.get("host", "claude"), "%s-alt" % seats.get("host", "claude")]
    adv = rot[index % len(rot)]
    crit = rot[(index + 1) % len(rot)]
    if crit == adv:
        crit = "%s-alt" % base_family(adv)
    return adv, crit


def premortem_family(seats, leader_author):
    for f in (seats.get("families") or []):
        if f != leader_author and base_family(f) != base_family(leader_author):
            return f
    return "%s-alt" % base_family(leader_author or seats.get("host", "claude"))


def review_lens_families(seats, writer, lenses):
    """Families other than the writer, round-robin; the web lens goes to a web-capable family."""
    fams = [f for f in (seats.get("families") or []) if base_family(f) != base_family(writer)]
    if not fams:
        fams = ["%s-alt" % base_family(writer)]
    web = [f for f in (seats.get("web_families") or []) if base_family(f) != base_family(writer)]
    out = {}
    for i, lens in enumerate(lenses):
        if lens == "L1" and web:
            out[lens] = web[0]
        else:
            out[lens] = fams[i % len(fams)]
    return out


def stack_verify_family(seats, writer=None):
    web = seats.get("web_families") or []
    return web[0] if web else seats.get("host", "claude")


LIST_SEATS = ("researcher", "checker_pool", "screen_judges", "tournament_judges", "redteam_rotation", "arch_authors",
              "arch_judges")


def reseat_minimal(old, fresh, available, host):
    """Cross-host continue (6.10): keep every seat whose family is still available; re-seat only the seats whose
    family disappeared, taking replacements from `fresh` (a full assign() on what is left).
    Returns (seats, changes) with changes = [(seat key, old family, new family)]."""
    avail = set(available)
    alt = "%s-alt" % host

    def ok(f):
        return bool(f) and base_family(f) in avail

    out = dict(fresh)
    changes = []
    for key in LIST_SEATS:
        before = list(old.get(key) or [])
        if not before:
            continue
        pool = [f for f in (fresh.get(key) or []) + list(fresh.get("families") or []) if ok(f)]
        now = []
        keepers = [f for f in before if ok(f)]
        for f in before:
            if ok(f):
                now.append(f)
                continue
            if key in ("redteam_rotation", "checker_pool") and len(keepers) >= (2 if key == "redteam_rotation" else 1):
                changes.append((key, f, "(dropped)"))
                continue
            rep = next((c for c in pool if c not in now and c not in before), None) or alt
            now.append(rep)
            changes.append((key, f, rep))
        out[key] = now
    gens_old = dict(old.get("generators") or {})
    gens_new = dict(fresh.get("generators") or {})
    gens = {}
    for k, f in gens_old.items():
        if ok(f):
            gens[k] = f
        else:
            rep = gens_new.get(k) if ok(gens_new.get(k)) else alt
            gens[k] = rep
            changes.append(("generators." + k, f, rep))
    for k, f in gens_new.items():
        gens.setdefault(k, f)
    out["generators"] = gens
    prop_old = dict(old.get("proposal") or {})
    prop_new = dict(fresh.get("proposal") or {})
    prop = {}
    for k in ("drafter", "redteam"):
        f = prop_old.get(k)
        prop[k] = f if ok(f) else prop_new.get(k)
        if f and not ok(f):
            changes.append(("proposal." + k, f, prop[k]))
    rub = []
    for f in prop_old.get("rubric") or []:
        if ok(f):
            rub.append(f)
        else:
            rep = next((c for c in prop_new.get("rubric") or [] if c not in rub), alt)
            rub.append(rep)
            changes.append(("proposal.rubric", f, rep))
    prop["rubric"] = rub or list(prop_new.get("rubric") or [alt])
    out["proposal"] = prop
    for key in ("arch_archetypes", "arch_writer", "s1_engine"):
        if old.get(key) is not None:
            out[key] = old[key]
    if old.get("arch_writer") and not ok(old.get("arch_writer")):
        out["arch_writer"] = host
        changes.append(("arch_writer", old.get("arch_writer"), host))
    return out, changes


def reseat(seats_old, seats_new):
    """Differences between two seat maps (for run.json.provisional after a cross-host continue)."""
    changes = []
    for key in ("screen_judges", "tournament_judges", "researcher", "checker_pool", "redteam_rotation",
                "arch_authors", "arch_judges"):
        if seats_old.get(key) != seats_new.get(key):
            changes.append((key, seats_old.get(key), seats_new.get(key)))
    go, gn = seats_old.get("generators") or {}, seats_new.get("generators") or {}
    for k in sorted(set(go) | set(gn)):
        if go.get(k) != gn.get(k):
            changes.append(("generators." + k, go.get(k), gn.get(k)))
    return changes
