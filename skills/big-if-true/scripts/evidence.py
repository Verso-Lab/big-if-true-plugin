#!/usr/bin/env python3
"""evidence.py — keyless lookups against the primary records fact-checks
keep needing. Each subcommand prints a short, citable result and the
exact URL queried. Stdlib only. No keys, except factcheck (a free one)
and an optional one for courtlistener.

  wayback URL [--at YYYYMMDD]   nearest archived snapshot of a page (Internet Archive)
  wayback-save URL              ask the Internet Archive to capture a page now
  crossref "title or query"     does a paper exist? DOI, journal, date, authors
  doi 10.xxxx/yyy               resolve a DOI to its record
  pubmed "query"                PubMed search: PMIDs, titles, journals, dates
  arxiv "query"                 arXiv search: ids, titles, dates
  edgar "phrase" [--from DATE]  SEC full-text search of filings since 2001
  wikidata "name"               entity lookup: description, Wikidata id
  factcheck "claim text"        Google Fact Check Tools (needs FACTCHECK_API_KEY)
  courtlistener "query"         US court opinions (COURTLISTENER_API_KEY raises limits)
  blocked URL                   the browser could not read this page: record it and move on
  blocked URL --settled         …the claim was settled elsewhere; the page is no longer needed
  blocked URL --unreachable     …nothing a person could do would open it
  blocked URL --needs-user "sign in"   …a login or a cleared check would open it: it goes in the ask
  blocked URL --opened / --skipped     …after the user replied: read, or left as is
  blocked --no-browser          no browser this session: every open entry becomes unreachable

Everything printed is a lead to open and read, not a verdict.
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET

UA = "BigIfTrue/1.0 (fact-checking; +https://verso.ink)"


def get(url, headers=None, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    # URLs carry API keys in the query and may carry logins; the exception text
    # can echo the URL. Keep the host, the path and the HTTP status only.
    u = urllib.parse.urlsplit(url)
    sys.exit(f"fetch failed: {u.hostname}{u.path}\n  {type(last).__name__} {getattr(last, 'code', '')}".rstrip())


def q(s):
    return urllib.parse.quote(s, safe="")


def out(url, lines):
    for l in lines:
        print(l)
    print(f"\nsource: {url}")


def cmd_wayback(a):
    url = f"https://archive.org/wayback/available?url={q(a.url)}" + (f"&timestamp={a.at}" if a.at else "")
    d = json.loads(get(url))
    snap = d.get("archived_snapshots", {}).get("closest")
    if not snap:
        return out(url, ["no snapshot found — try `wayback-save` to capture it now"])
    out(url, [f"snapshot: {snap['url']}", f"captured: {snap['timestamp']}  status: {snap['status']}"])


def cmd_wayback_save(a):
    url = f"https://web.archive.org/save/{a.url}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=120)
        out(url, [f"saved: {r.headers.get('Content-Location') or r.geturl()}"])
    except Exception as e:  # noqa
        u = urllib.parse.urlsplit(a.url)
        out(url, [f"save request failed for {u.hostname}{u.path}: {type(e).__name__} {getattr(e, 'code', '')}".rstrip()
                  + "; open the URL in a browser to capture it"])


def _crossref_items(url):
    d = json.loads(get(url))
    return [i for i in d["message"].get("items", [d["message"]] if "items" not in d["message"] else [])]


def _paper_line(i):
    title = (i.get("title") or ["(untitled)"])[0]
    auth = ", ".join(f"{p.get('family','')}" for p in (i.get("author") or [])[:3])
    date = "-".join(str(x) for x in (i.get("issued", {}).get("date-parts") or [[""]])[0])
    return f"{i.get('DOI','')}  {date}  {i.get('container-title', [''])[0]}\n    {title}\n    {auth}"


def cmd_crossref(a):
    url = f"https://api.crossref.org/works?query.bibliographic={q(a.query)}&rows={a.n}&mailto=team@verso.ink"
    out(url, [_paper_line(i) for i in _crossref_items(url)] or ["no results"])


def cmd_doi(a):
    url = f"https://api.crossref.org/works/{q(a.doi)}"
    d = json.loads(get(url))["message"]
    out(url, [_paper_line(d), f"type: {d.get('type')}  publisher: {d.get('publisher')}  url: {d.get('URL')}"])


def cmd_pubmed(a):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    url = f"{base}esearch.fcgi?db=pubmed&term={q(a.query)}&retmax={a.n}&retmode=json&sort=relevance"
    ids = json.loads(get(url))["esearchresult"]["idlist"]
    if not ids:
        return out(url, ["no results"])
    s = json.loads(get(f"{base}esummary.fcgi?db=pubmed&id={','.join(ids)}&retmode=json"))["result"]
    lines = [f"PMID {i}  {s[i].get('pubdate','')}  {s[i].get('fulljournalname','')}\n    {s[i].get('title','')}"
             for i in ids]
    out(url, lines + ["\nopen: https://pubmed.ncbi.nlm.nih.gov/<PMID>/"])


def cmd_arxiv(a):
    url = f"https://export.arxiv.org/api/query?search_query=all:{q(a.query)}&max_results={a.n}"
    root = ET.fromstring(get(url))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    lines = []
    for e in root.findall("a:entry", ns):
        lines.append(f"{e.find('a:id', ns).text}  {e.find('a:published', ns).text[:10]}\n    "
                     f"{' '.join(e.find('a:title', ns).text.split())}")
    out(url, lines or ["no results"])


def cmd_edgar(a):
    url = (f"https://efts.sec.gov/LATEST/search-index?q={q(a.phrase)}&dateRange=custom"
           f"&startdt={a.frm}&enddt=2099-12-31")
    d = json.loads(get(url))
    hits = d.get("hits", {}).get("hits", [])
    lines = [f"total hits: {d.get('hits', {}).get('total', {}).get('value')}"]
    for h in hits[:a.n]:
        s = h["_source"]
        adsh, fname = h["_id"].split(":", 1)
        cik = (s.get("ciks") or [""])[0].lstrip("0")
        link = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-', '')}/{fname}"
        lines.append(f"{s.get('file_date')}  {s.get('form') or s.get('form_type')}  {'; '.join(s.get('display_names', []))[:80]}\n    {link}")
    out(url, lines)


def cmd_wikidata(a):
    url = f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={q(a.name)}&language={a.lang}&format=json&limit={a.n}"
    d = json.loads(get(url))
    out(url, [f"{e['id']}  {e.get('label','')} — {e.get('description','')}" for e in d.get("search", [])] or ["no match"])


def cmd_factcheck(a):
    key = os.environ.get("FACTCHECK_API_KEY")
    if not key:
        sys.exit("needs FACTCHECK_API_KEY (free: console.cloud.google.com → Fact Check Tools API); "
                 "or search by hand at https://toolbox.google.com/factcheck/explorer")
    url = f"https://factchecktools.googleapis.com/v1alpha1/claims:search?query={q(a.claim)}&pageSize={a.n}&key={key}"
    d = json.loads(get(url))
    lines = []
    for c in d.get("claims", []):
        for r in c.get("claimReview", []):
            lines.append(f"{r.get('reviewDate','')[:10]}  {r.get('publisher',{}).get('name','')}: {r.get('textualRating','')}\n"
                         f"    claim: {c.get('text','')[:120]}\n    {r.get('url','')}")
    out(url.replace(key, "<key>"), lines or ["no published fact-checks match"])


def cmd_courtlistener(a):
    key = os.environ.get("COURTLISTENER_API_KEY")
    url = f"https://www.courtlistener.com/api/rest/v4/search/?q={q(a.query)}&type=o"
    h = {"Authorization": f"Token {key}"} if key else {}
    d = json.loads(get(url, headers=h))
    lines = [f"{r.get('dateFiled','')}  {r.get('court','')}  {r.get('caseName','')}\n    https://www.courtlistener.com{r.get('absolute_url','')}"
             for r in d.get("results", [])[:a.n]]
    out(url, lines or ["no results (anonymous access is rate-limited; a free key lifts it)"])


# The ledger lives in the working directory, next to source.txt and
# check.json; assemble.py looks for it in the same place.
LEDGER = "blocked.json"
FLAGS = ("settled", "unreachable", "needs_user", "opened", "skipped")


def cmd_blocked(a):
    """The ledger of pages the browser could not read. assemble.py refuses to
    build while an entry is still 'blocked' (not yet triaged) or
    'needs_user' (the ask has not been answered)."""
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else []
    if a.no_browser:
        for e in led:
            if e["status"] == "blocked":
                e["status"] = "unreachable"
    elif a.url:
        e = next((e for e in led if e["url"] == a.url), None)
        if e is None:
            e = {"url": a.url, "status": "blocked"}
            led.append(e)
        for f in FLAGS:
            v = getattr(a, f)
            if v:
                e["status"] = f
                if f == "needs_user":
                    e["needs"] = v
    json.dump(led, open(LEDGER, "w"), indent=1)
    for e in led:
        print(f"{e['status']:<12} {e['url']}" + (f"  — {e['needs']}" if e.get("needs") else ""))
    if not led:
        print("no blocked pages recorded")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=5, help="results to show")
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("wayback"); x.add_argument("url"); x.add_argument("--at"); x.set_defaults(f=cmd_wayback)
    x = s.add_parser("wayback-save"); x.add_argument("url"); x.set_defaults(f=cmd_wayback_save)
    x = s.add_parser("crossref"); x.add_argument("query"); x.set_defaults(f=cmd_crossref)
    x = s.add_parser("doi"); x.add_argument("doi"); x.set_defaults(f=cmd_doi)
    x = s.add_parser("pubmed"); x.add_argument("query"); x.set_defaults(f=cmd_pubmed)
    x = s.add_parser("arxiv"); x.add_argument("query"); x.set_defaults(f=cmd_arxiv)
    x = s.add_parser("edgar"); x.add_argument("phrase"); x.add_argument("--from", dest="frm", default="2001-01-01"); x.set_defaults(f=cmd_edgar)
    x = s.add_parser("wikidata"); x.add_argument("name"); x.add_argument("--lang", default="en"); x.set_defaults(f=cmd_wikidata)
    x = s.add_parser("factcheck"); x.add_argument("claim"); x.set_defaults(f=cmd_factcheck)
    x = s.add_parser("courtlistener"); x.add_argument("query"); x.set_defaults(f=cmd_courtlistener)
    x = s.add_parser("blocked"); x.add_argument("url", nargs="?")
    for f in ("settled", "unreachable", "opened", "skipped", "no-browser"):
        x.add_argument("--" + f, dest=f.replace("-", "_"), action="store_true")
    x.add_argument("--needs-user", dest="needs_user"); x.set_defaults(f=cmd_blocked)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
