#!/usr/bin/env python3
"""Big If True report assembler.

The checked text flows through this script as data — it is copied from the
source file and never passes through the model's own writing, which is what
guarantees the annotated article is verbatim.

Usage:
  python3 assemble.py density SOURCE.txt CLAIMS.md
      Pass 1 check, run BEFORE verifying: every claim's quote must sit in
      the text exactly once, the list must meet the words-per-claim
      standard, and the list is recorded in pass1.json in the working
      directory. The build refuses a check.json that drops or merges any
      recorded claim: each needs its own claim whose quote overlaps its
      Pass 1 quote. Re-running density may add claims, never remove one.
  python3 assemble.py build SOURCE.txt CHECK.json OUT.html
      (the template is ../assets/template.html; pass a fourth path to
      override: build SOURCE.txt CHECK.json TEMPLATE.html OUT.html)
  python3 assemble.py export md|csv|json|comments SOURCE.txt CHECK.json OUT
      The same findings in another shape, only when the user asks:
      md   the text report (the fallback format in SKILL.md), for docs,
           email, Slack; csv  one row per claim, for spreadsheets and
           corrections logs; json  the findings with article-order
           numbers and resolved sources, for tooling; comments  the
           needs_review findings as ready-to-post document comments:
           `text` (plain, for Google Docs) and `markdown` (inline links,
           for Notion), with a `find` fragment and a start...end
           `selection` that locate the passage — see references/write-back.md.
      Same validation and article order as build.

SOURCE.txt  The checked text, exactly as the user provided it.
            Paragraphs separated by blank lines.

CLAIMS.md   The Pass 1 list (references/extraction.md). A claim is a line
            "- [fact] ..." or "- [attribution] ...", followed by a line
            "> " and the exact quote it comes from. Every other line
            (paragraph headings, discard log) is free text.

CHECK.json  One file, every field named. Claims are anchored by quotation —
            no ids, no sentence numbers; the build sorts claims into
            article order by quote position and derives ids from that,
            so the array's order never matters:
{
  "page_title": "<Subject>, Checked",
  "title": headline, "source": outlet, "byline": author or "",
  "published": date shown or "", "checked": today,
  "refs": {key: [publisher label, url], ...},
  "thin_text": only for a genuinely thin text (heavy rhetoric, lists,
               captions): one line saying why — the density gate asks for
               it before building a report above 20 words per claim,
  "claims": [
    {"verdict": "r"|"c"|"s",     r=needs_review c=could_not_verify s=supported
     "claim":  the claim text,
     "why":    one-or-two sentence rationale,
     "refs":   [ref keys] (empty allowed when "why" explains why),
     "quote":  the exact stretch of the source text this claim comes from,
               copied verbatim — a phrase when the claim is part of a
               sentence, the sentence when it is the whole point. If the
               build says the quote is ambiguous, extend it until unique.},
    ...
  ]
}
"""
import difflib, html, json, os, re, sys
from collections import Counter

# Scripts without word spaces (Chinese, Japanese, Thai, Khmer, Lao, Burmese)
# would count as a handful of "words" and wreck the density gate. Count a
# CJK/Thai character as half a word — the usual rough conversion — and
# whitespace tokens for everything else.
_NOSPACE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\u0e00-\u0e7f\u0e80-\u0eff\u1780-\u17ff\u1000-\u109f]')

def word_count(text):
    nospace = len(_NOSPACE.findall(text))
    rest = _NOSPACE.sub(' ', text)
    return len(rest.split()) + nospace // 2

VERDICTS = {"r", "c", "s"}
QUOTE_OPENERS = ('“', '"', '‘', "'", '„', '«')


def paragraphs(text):
    return [p for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]


def closest(needle, hay):
    cands = [hay[i:i + len(needle) + 20] for i in range(0, max(1, len(hay) - 10), 25)]
    best = difflib.get_close_matches(needle, cands, n=1, cutoff=0.5)
    return best[0].strip() if best else None


DENSITY_FAIL = (
    "  Thorough extraction of assertive prose runs 12-15 words per claim;\n"
    "  above 20 almost always means Pass 1 was compressed. Re-open Pass 1:\n"
    "  re-walk the paragraphs with the fewest claims, discard log in hand,\n"
    "  and extract the quantifiers, definitions, premises, identity facts,\n"
    "  and background facts that were passed over.\n"
    "  Only if this text is genuinely thin (heavy rhetoric, lists, captions)\n"
    "  state why in check.json — \"thin_text\": \"<one-line reason>\" — and re-run."
)


def norm_map(t):
    """Whitespace-normalized view of a paragraph, mapped back to original
    offsets, so quotes tolerate line wraps and double spaces."""
    out, idx, i = [], [], 0
    while i < len(t):
        if t[i].isspace():
            while i < len(t) and t[i].isspace():
                i += 1
            if out and i < len(t):
                out.append(" "); idx.append(i - 1)
        else:
            out.append(t[i]); idx.append(i); i += 1
    return "".join(out), idx


def nq(quote):
    return " ".join(quote.split())


def locator(text):
    norm_paras = [norm_map(p) for p in paragraphs(text)]

    def locate(quote):
        q = nq(quote)
        hits = []
        for pi, (np, idx) in enumerate(norm_paras):
            for m in re.finditer(re.escape(q), np):
                a = m.start()
                hits.append((pi, idx[a], idx[a + len(q) - 1] + 1))
        return q, hits
    return locate, norm_paras


def quote_error(label, q, hits, norm_paras):
    if len(hits) == 0:
        hint = closest(q, " ".join(np for np, _ in norm_paras))
        return (f"{label}: quote not found in the source text: {q!r}"
                + (f" — closest passage: {hint!r}" if hint else ""))
    if len(hits) > 1:
        return f"{label}: quote appears {len(hits)} times — extend it until it is unique: {q!r}"
    return None


CLAIM_LINE = re.compile(r"^\s*[-*]\s*\[(fact|attribution)\]\s*(.+?)\s*$", re.I)
QUOTE_LINE = re.compile(r"^\s*>\s?(.*?)\s*$")
PASS1 = "pass1.json"


def read_claims(claims_f):
    """[(line number, claim, quote)] from a Pass 1 claims file."""
    lines = open(claims_f, encoding="utf-8").read().splitlines()
    claims, errs = [], []
    for i, line in enumerate(lines):
        m = CLAIM_LINE.match(line)
        if not m:
            continue
        nxt = QUOTE_LINE.match(lines[i + 1]) if i + 1 < len(lines) else None
        if not nxt or not nxt.group(1).strip():
            errs.append(f"line {i + 1}: claim has no quote line under it (\"> \" and the exact words): {m.group(2)[:70]!r}")
            continue
        claims.append((i + 1, m.group(2), nxt.group(1)))
    return claims, errs


def cmd_density(src_f, claims_f):
    text = open(src_f).read()
    claims, errs = read_claims(claims_f)
    locate, norm_paras = locator(text)
    for line, _, quote in claims:
        q, hits = locate(quote)
        err = quote_error(f"line {line}", q, hits, norm_paras)
        if err:
            errs.append(err)
    if not claims and not errs:
        errs.append("no claims found: each claim is a line \"- [fact] ...\" or \"- [attribution] ...\" "
                    "followed by a line \"> \" with its exact quote")
    if errs:
        sys.exit("ERRORS in the claims file — fix and re-run:\n  " + "\n  ".join(errs))
    quotes = [nq(q) for _, _, q in claims]
    if os.path.exists(PASS1):
        before = json.load(open(PASS1))["quotes"]
        dropped = list((Counter(before) - Counter(quotes)).elements())
        if dropped:
            sys.exit("The claims file has fewer claims than the list already recorded. Pass 1 can grow, "
                     "never shrink: restore these claims (split, never merged or removed):\n  "
                     + "\n  ".join(repr(q) for q in dropped))
    words = word_count(text)
    n = len(claims)
    wpc = words / max(1, n)
    json.dump({"claims": n, "quotes": quotes}, open(PASS1, "w"), indent=1)
    print(f"recorded {n} claims in {PASS1}: each needs its own verdict in check.json")
    print(f"density: {wpc:.0f} words per claim ({words} words, {n} claims)")
    if wpc > 20:
        sys.exit("THIN EXTRACTION — do not verify this list yet.\n" + DENSITY_FAIL)
    if wpc > 15:
        print("NOTE: passable but on the thin side — worth one re-walk of the"
              " paragraphs with the fewest claims before verifying.")
    else:
        print("OK: within the 12-15 words-per-claim band of thorough extraction.")


LEDGER_RESOLVED = {"settled", "unreachable", "opened", "skipped"}


def blocked_gate():
    """Pages the browser could not read live in blocked.json in the working
    directory, the same place evidence.py blocked writes it (the check's
    files all live where the scripts are run from). Before the report, each
    one is triaged: settled elsewhere, unreachable, or needs the user. A
    page that needs the user means the turn ends with an ask; a page not
    yet triaged means the check is not finished."""
    path = os.path.abspath("blocked.json")
    if not os.path.exists(path):
        sys.exit("No browser ledger (blocked.json in the working directory). Every page that "
                 "would not fetch goes to the browser, and every page the browser could not "
                 "read goes in the ledger:\n"
                 "  python3 scripts/evidence.py blocked URL\n"
                 "Go back over the pages that would not fetch. Then run\n"
                 "  python3 scripts/evidence.py blocked\n"
                 "from this directory to list the ledger (empty is fine if nothing was "
                 "blocked) and build again.")
    led = json.load(open(path))
    unknown = [f"{e.get('url')}: {e.get('status')!r}" for e in led
               if e.get("status") not in LEDGER_RESOLVED | {"blocked", "needs_user"}]
    if unknown:
        sys.exit("The ledger has entries with a status evidence.py never writes. Record pages only with\n"
                 "  python3 scripts/evidence.py blocked URL [--settled | --unreachable | --needs-user \"...\" | --opened | --skipped]\n  "
                 + "\n  ".join(unknown))
    untriaged = [e["url"] for e in led if e.get("status") == "blocked"]
    if untriaged:
        sys.exit("The ledger has pages not yet triaged. For each, decide what a verdict still needs:\n  "
                 + "\n  ".join(untriaged) +
                 "\n  python3 scripts/evidence.py blocked URL --settled      claim settled from another source\n"
                 "  python3 scripts/evidence.py blocked URL --unreachable  nothing a person could do would open it\n"
                 "  python3 scripts/evidence.py blocked URL --needs-user \"sign in\"   a login or a cleared check would open it\n"
                 "  python3 scripts/evidence.py blocked --no-browser       no browser in this session")
    need = [e for e in led if e.get("status") == "needs_user"]
    if need:
        lines = [f"  {i}. {e['url']} — {e.get('needs', 'sign in or clear the check')}"
                 for i, e in enumerate(need, start=1)]
        sys.exit("STOP — the report cannot be built yet: "
                 f"{len(need)} page(s) need the user. Open each in its own browser tab, then end the turn "
                 "with this message, and continue when they reply:\n\n"
                 f"  I need your help with {len(need)} page(s); each is open in its own tab:\n"
                 + "\n".join(lines) +
                 "\n  Say done when you're through, or skip for any you'd rather leave.\n\n"
                 "When they reply: read each tab, finish those claims, then mark each page\n"
                 "  python3 scripts/evidence.py blocked URL --opened   (or --skipped)\n"
                 "and build again.")


def unanswered(pass1_spans, check_spans):
    """Pass 1 claims left without a check.json claim of their own. Each
    Pass 1 claim needs a distinct check.json claim whose quote overlaps
    its quote in the text: a narrowed or widened quote still answers it,
    but one check.json claim cannot answer two Pass 1 claims, which is
    what a merge is. Maximum matching, so the assignment is never
    order-dependent."""
    adj = [[j for j, (cp, cs, ce) in enumerate(check_spans) if cp == pp and cs < pe and ps < ce]
           for pp, ps, pe in pass1_spans]
    owner = {}

    def assign(i, seen):
        for j in adj[i]:
            if j not in seen:
                seen.add(j)
                if j not in owner or assign(owner[j], seen):
                    owner[j] = i
                    return True
        return False
    return [i for i in range(len(pass1_spans)) if not assign(i, set())]


def pass1_gate(locate, anchors):
    """Every claim recorded at Pass 1 gets its own verdict."""
    if not os.path.exists(PASS1):
        sys.exit(f"No Pass 1 record ({PASS1} in the working directory). Run\n"
                 "  python3 scripts/assemble.py density source.txt claims.md\n"
                 "on the Pass 1 claims file first; it records the list every verdict answers to.")
    quotes = json.load(open(PASS1))["quotes"]
    spans = [locate(q)[1] for q in quotes]
    if any(len(h) != 1 for h in spans):
        sys.exit(f"{PASS1} does not match this source text. Run density again on the claims file for this text.")
    missing = unanswered([h[0] for h in spans], list(anchors.values()))
    if missing:
        sys.exit(f"{len(missing)} claim(s) on the Pass 1 list have no verdict of their own in check.json. "
                 "Each needs its own claim, anchored on a quote that overlaps its Pass 1 quote; one "
                 "claim cannot answer two, because a merged claim hides the verdict of the one it "
                 "swallowed. Split each back out, with its own verdict and rationale:\n  "
                 + "\n  ".join(repr(quotes[i]) for i in missing))


def prepare(src, check_f):
    """Validate CHECK.json against SOURCE.txt and put the claims in article
    order. Shared by build and export so every output agrees on numbering."""
    blocked_gate()
    text = open(src).read()
    check = json.load(open(check_f))
    refs = check.get("refs", {})
    claims_in = check.get("claims", [])
    paras_text = paragraphs(text)

    locate, norm_paras = locator(text)

    errs = []
    for field in ("title", "checked"):
        if not str(check.get(field, "") or "").strip():
            errs.append(f"missing '{field}' at the top of check.json")
    if not isinstance(refs, dict):
        errs.append("'refs' must be an object: {key: [publisher label, url]}")
        refs = {}
    for k, ref in refs.items():
        ok = (isinstance(ref, list) and len(ref) == 2 and all(isinstance(x, str) and x.strip() for x in ref)
              and re.match(r"https?://", ref[1]))
        if not ok:
            errs.append(f"ref {k!r} must be [publisher label, url] with an http(s) url")
    claims_out = []
    anchors = {}   # id -> (para_idx, start, end) within that paragraph
    for idx, c in enumerate(claims_in, start=1):
        for field in ("verdict", "claim", "why", "refs", "quote"):
            if field not in c:
                errs.append(f"claim {idx}: missing field '{field}'")
        v = c.get("verdict")
        if v not in VERDICTS:
            errs.append(f"claim {idx}: verdict must be 'r', 'c' or 's' (got {v!r})")
        for k in c.get("refs", []):
            if k not in refs:
                errs.append(f"claim {idx}: ref key {k!r} not in refs")
        if v == "s" and not c.get("refs"):
            errs.append(f"claim {idx}: supported needs at least one source in refs "
                        "(two independent, or one primary and definitive)")
        q = c.get("quote") or ""
        if q:
            _, hits = locate(q)
            err = quote_error(f"claim {idx}", q, hits, norm_paras)
            if err:
                errs.append(err)
            else:
                anchors[idx] = hits[0]
        elif "quote" in c:
            errs.append(f"claim {idx}: quote is empty")
        claims_out.append([idx, v, c.get("claim", ""), c.get("why", ""), c.get("refs", []), q])
    if errs:
        sys.exit("ERRORS in CHECK.json — fix and re-run:\n  " + "\n  ".join(errs))
    pass1_gate(locate, anchors)

    # Article order is derived, never trusted: sort claims by where their
    # quote sits in the text and assign ids from that, so margin numbers,
    # the claims list, and the spine always follow the article no matter
    # how check.json's array was ordered.
    order = sorted(anchors, key=lambda i: anchors[i])
    id_map = {old_id: new_id for new_id, old_id in enumerate(order, start=1)}
    claims_out = sorted(([id_map[c[0]]] + c[1:] for c in claims_out), key=lambda c: c[0])
    anchors = {id_map[i]: p for i, p in anchors.items()}

    # Pass 1 density gate — the only mechanical guard extraction has.
    # Thorough news/interview extraction runs 12-15 words per claim.
    words = word_count(text)
    wpc = words / max(1, len(claims_out))
    thin = str(check.get("thin_text", "") or "").strip()
    if wpc > 20 and not thin:
        sys.exit(
            f"DENSITY GATE: {wpc:.0f} words per claim ({words} words, {len(claims_out)} claims) — no report built.\n"
            + DENSITY_FAIL
        )
    return dict(text=text, check=check, refs=refs, claims=claims_out, anchors=anchors,
                paras_text=paras_text, words=words, wpc=wpc, thin=thin)


def cmd_build(src, check_f, tpl_f, out_f):
    d = prepare(src, check_f)
    text, check, refs, anchors = d["text"], d["check"], d["refs"], d["anchors"]
    paras_text, words, wpc, thin = d["paras_text"], d["words"], d["wpc"], d["thin"]
    claims_out = d["claims"]

    # partition each paragraph by the claim intervals covering it
    paras = []
    for pi, par in enumerate(paras_text):
        intervals = [(s, e, cid) for cid, (p2, s, e) in anchors.items() if p2 == pi]
        is_quote_graf = par.lstrip().startswith(QUOTE_OPENERS)
        if not intervals:
            paras.append([[par, 0, "q"] if is_quote_graf else [par, 0]])
            continue
        bounds = sorted({0, len(par), *[x for s, e, _ in intervals for x in (s, e)]})
        segs = []
        for a, b in zip(bounds, bounds[1:]):
            ids = sorted(cid for s, e, cid in intervals if s <= a and b <= e)
            seg = [par[a:b], ids if ids else 0]
            if segs and segs[-1][1] == seg[1]:
                segs[-1][0] += seg[0]
            else:
                segs.append(seg)
        if is_quote_graf:
            for seg in segs:
                seg.append("q")
        paras.append(segs)

    payload = {
        "title": check.get("title", ""), "source": check.get("source", ""),
        "byline": check.get("byline", ""), "published": check.get("published", ""),
        "checked": check.get("checked", ""), "refs": refs,
        "claims": claims_out, "paragraphs": paras,
        # the page's Export menu copies these; built here so page and files agree
        "exports": {fmt: export_body(fmt, d) for fmt in ("md", "csv", "json")},
    }
    tpl = open(tpl_f).read()
    # "<\/" keeps any "</script>" inside the article from ending the data block
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out = (tpl
           .replace("__REPORT_TITLE__", html.escape(check.get("page_title", check.get("title", "Checked"))))
           .replace("__BIG_IF_TRUE_DATA__", data))
    open(out_f, "w").write(out)
    print(f"OK: {out_f} · {len(claims_out)} claims · {len(paras)} paragraphs")

    # Pass 1 coverage report (the hard density gate already ran above)
    print(f"   density: {wpc:.0f} words per claim ({words} words)")
    if thin:
        print(f"   thin_text acknowledged: {thin}")
    elif wpc > 15:
        print("   NOTE: thorough extraction of assertive prose runs 12-15 words per"
              " claim. This is passable but on the thin side — worth one re-walk of"
              " the paragraphs with the fewest claims.")
    covered = {pi for pi, _, _ in anchors.values()}
    bare = [(pi, paras_text[pi]) for pi in range(len(paras_text)) if pi not in covered]
    # short paragraphs (headers, section labels, one-line questions) are
    # often legitimately claim-free; flag the substantial ones
    substantial = [(pi, p) for pi, p in bare if word_count(p) >= 25]
    if substantial:
        print(f"   NOTE: {len(substantial)} substantial paragraph(s) carry no anchored claims:")
        for pi, p in substantial[:6]:
            preview = " ".join(p.split())[:90]
            print(f"     - paragraph {pi + 1}: \"{preview}…\"")
        if len(substantial) > 6:
            print(f"     … and {len(substantial) - 6} more")
        print("     Confirm each was consciously judged (discard log), not skipped.")


VERDICT_WORD = {"r": "needs_review", "c": "could_not_verify", "s": "supported"}
FOOTER = ("*Checked with the [Big If True](https://verso.ink) method by Verso. "
          "AI can make mistakes, judge the evidence through the links.*")


def export_body(fmt, d):
    """The findings in prepare()'s output d as md, csv or json text."""
    check, refs = d["check"], d["refs"]
    rows = [{"n": n, "verdict": VERDICT_WORD[v], "claim": claim, "why": why, "quote": q,
             "sources": [{"label": refs[k][0], "url": refs[k][1]} for k in keys]}
            for n, v, claim, why, keys, q in d["claims"]]
    meta = {k: check.get(k, "") for k in ("title", "source", "byline", "published", "checked")}
    counts = {w: sum(r["verdict"] == w for r in rows) for w in VERDICT_WORD.values()}

    if fmt == "json":
        body = json.dumps({**meta, "counts": counts, "claims": rows}, ensure_ascii=False, indent=1) + "\n"
    elif fmt == "csv":
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["n", "verdict", "claim", "quote", "rationale", "sources", "source_urls"])
        for r in rows:
            w.writerow([r["n"], r["verdict"], r["claim"], r["quote"], r["why"],
                        "; ".join(s["label"] for s in r["sources"]),
                        " ".join(s["url"] for s in r["sources"])])
        body = "﻿" + buf.getvalue()   # BOM so Excel reads UTF-8
    elif fmt == "md":
        def srcs(r):
            return " Sources: " + ", ".join(f"[{s['label']}]({s['url']})" for s in r["sources"]) if r["sources"] else ""
        def full(r):
            return f"**{r['n']}. {r['claim']}** {r['why']}{srcs(r)}\n> {r['quote']}\n"
        def compact(r):
            return f"- **{r['n']}.** {r['claim']}{srcs(r)}"
        by = {w: [r for r in rows if r["verdict"] == w] for w in VERDICT_WORD.values()}
        line = " · ".join(x for x in (meta["source"], meta["byline"],
                                       f"Published {meta['published']}" if meta["published"] else "",
                                       f"Checked {meta['checked']}" if meta["checked"] else "") if x)
        parts = [f"## Fact-check: {meta['title']}", line,
                 f"Checked {len(rows)} claims: {counts['supported']} supported, "
                 f"{counts['needs_review']} need review, {counts['could_not_verify']} could not be verified.", ""]
        parts += [f"### ⚠️ Needs review ({counts['needs_review']})", ""] + [full(r) for r in by["needs_review"]]
        parts += [f"### ❓ Could not verify ({counts['could_not_verify']})", ""] + [full(r) for r in by["could_not_verify"]]
        parts += [f"### ✓ Supported ({counts['supported']})", ""] + [compact(r) for r in by["supported"]]
        parts += ["", "---", "", FOOTER, ""]
        body = "\n".join(p for p in parts if p is not None)
    elif fmt == "comments":
        body = json.dumps({**meta, "comments": [comment_for(r, d["text"]) for r in rows if r["verdict"] == "needs_review"]},
                          ensure_ascii=False, indent=1) + "\n"
    else:
        sys.exit(f"unknown export format {fmt!r}: use md, csv, json or comments")
    return body


_CURLY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})


def _norm(t):
    return " ".join(t.translate(_CURLY).split())


def find_string(quote, text, min_words=5, max_words=12):
    """A short literal fragment of the quote for a document's find box:
    curly quotes straightened (editors match literally), starting after
    any opening punctuation, and extended word by word until it occurs
    exactly once in the text — so a find lands on the right passage."""
    q = _norm(quote).strip("\"' ")
    hay = _norm(text)
    ws = q.split(" ")
    for n in range(min(min_words, len(ws)), min(max_words, len(ws)) + 1):
        frag = " ".join(ws[:n]).rstrip(".;:!?,")
        if hay.count(frag) == 1:
            return frag
    return q


VERDICT_LABEL = {"needs_review": "Needs Review", "could_not_verify": "Could Not Verify", "supported": "Supported"}


def sources_block(srcs, links):
    """links="plain": label and bare URL on separate lines, numbered when
    there are several (Google Docs comments, clipboard). links="markdown":
    inline links on one line (Notion)."""
    if not srcs:
        return ""
    if links == "markdown":
        items = " · ".join(f"[{s['label']}]({s['url']})" for s in srcs)
        return ("Source: " if len(srcs) == 1 else "Sources: ") + items
    if len(srcs) == 1:
        return f"Source: {srcs[0]['label']}\n{srcs[0]['url']}"
    return "Sources:\n" + "\n".join(f"{i}. {s['label']}\n   {s['url']}" for i, s in enumerate(srcs, 1))


def finding_text(r, posted_by_claude=False, links="plain"):
    """One finding as a margin note or a paste-ready snippet: the verdict,
    the rationale, the sources, a provenance line."""
    prov = "Fact-check by Big If True (verso.ink)." + (" Comment posted by Claude." if posted_by_claude else "")
    return "\n\n".join(p for p in (f"Verdict: {VERDICT_LABEL[r['verdict']]}", r["why"],
                                    sources_block(r["sources"], links), prov) if p)


def comment_for(r, text):
    body = finding_text(r, posted_by_claude=True)
    md = finding_text(r, posted_by_claude=True, links="markdown")
    q = _norm(r["quote"]).strip("\"' ")
    selection = q if len(q) <= 24 else f"{q[:10]}...{q[-10:]}"
    return {"n": r["n"], "quote": r["quote"], "find": find_string(r["quote"], text),
            "selection": selection, "text": body, "markdown": md}


def cmd_export(fmt, src, check_f, out_f):
    d = prepare(src, check_f)
    open(out_f, "w", encoding="utf-8").write(export_body(fmt, d))
    print(f"OK: {out_f} · {fmt} · {len(d['claims'])} claims")


if __name__ == "__main__":
    DEFAULT_TPL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "template.html")
    if len(sys.argv) == 6 and sys.argv[1] == "build":
        cmd_build(*sys.argv[2:6])
    elif len(sys.argv) == 5 and sys.argv[1] == "build":
        cmd_build(sys.argv[2], sys.argv[3], DEFAULT_TPL, sys.argv[4])
    elif len(sys.argv) == 6 and sys.argv[1] == "export":
        cmd_export(*sys.argv[2:6])
    elif len(sys.argv) == 4 and sys.argv[1] == "density":
        cmd_density(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
