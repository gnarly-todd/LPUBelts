#!/usr/bin/env python3
"""
Rebuild the lock snapshot embedded in belt-explorer.html from the live LPU list.

    python3 refresh-lpu-data.py                    # fetch and update in place
    python3 refresh-lpu-data.py --dry-run          # show what would change
    python3 refresh-lpu-data.py --from-file p.html # use a saved copy instead

Standard library only. No install step.
"""

import argparse, datetime, html.parser, json, os, re, sys, urllib.request

SRC = "https://lpubelts.com/locks/all-locks.html"
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "belt-explorer.html")

# The canonical ladder. Headings outside this list are kept only if they hold locks,
# which is how a future Dan or Tier belt would appear without a code change.
CANON = ["White", "Yellow", "Orange", "Green", "Blue", "Purple", "Brown", "Red",
         "Black 1", "Black 2", "Black 3", "Black 4", "Black 5", "Unranked"]

ID_RE = re.compile(r"/locks/([0-9a-f]{8})\.html")


class Extract(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.belts = list(CANON)
        self.locks, self.seen = [], set()
        self.cur, self.mode, self.buf, self.href = -1, None, [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self.mode, self.buf = "h", []
        elif tag == "a":
            self.href = dict(attrs).get("href", "")
            self.mode, self.buf = "a", []

    def handle_data(self, d):
        if self.mode:
            self.buf.append(d)

    def handle_endtag(self, tag):
        text = "".join(self.buf).strip()
        if tag in ("h1", "h2", "h3", "h4") and self.mode == "h":
            name = re.sub(r"\s+Belt$", "", text, flags=re.I).strip()
            if name and not re.match(r"^(LPU|All Locks)", name, re.I):
                if name not in self.belts:
                    self.belts.append(name)
                self.cur = self.belts.index(name)
            self.mode = None
        elif tag == "a" and self.mode == "a":
            m = ID_RE.search(self.href or "")
            if m and self.cur >= 0 and text and m.group(1) not in self.seen:
                self.seen.add(m.group(1))
                self.locks.append({"id": m.group(1), "n": text, "b": self.cur})
            self.mode = None


def build(page_html, prev_count):
    p = Extract()
    p.feed(page_html)
    if len(p.locks) < max(300, int(prev_count * 0.6)):
        sys.exit("Refused: parsed only %d locks (expected near %d). The page format "
                 "probably changed \u2014 nothing was written." % (len(p.locks), prev_count))

    used = {l["b"] for l in p.locks}
    keep, remap = [], {}
    for i, name in enumerate(p.belts):
        if i < len(CANON) or i in used:          # drop invented headings that held no locks
            remap[i] = len(keep)
            keep.append(name)
    for l in p.locks:
        l["b"] = remap[l["b"]]
    p.locks.sort(key=lambda l: (l["b"], l["n"].lower()))

    return {"captured": datetime.date.today().isoformat(), "source": SRC,
            "belts": keep, "locks": p.locks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--app", default=APP)
    a = ap.parse_args()

    app = open(a.app, encoding="utf-8").read()
    m = re.search(r'(<script id="lpuData" type="application/json">)(.*?)(</script>)', app, re.S)
    if not m:
        sys.exit("Could not find the embedded data block in %s" % a.app)
    old = json.loads(m.group(2))

    if a.from_file:
        page = open(a.from_file, encoding="utf-8").read()
    else:
        req = urllib.request.Request(SRC, headers={"User-Agent": "belt-explorer-refresh/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode("utf-8", "replace")

    new = build(page, len(old["locks"]))

    before = {l["id"] for l in old["locks"]}
    after = {l["id"] for l in new["locks"]}
    moved = sum(1 for l in new["locks"]
                if l["id"] in before
                and old["belts"][next(o["b"] for o in old["locks"] if o["id"] == l["id"])]
                != new["belts"][l["b"]])

    print("was %d locks (captured %s)" % (len(old["locks"]), old["captured"]))
    print("now %d locks (captured %s)" % (len(new["locks"]), new["captured"]))
    print("  added   %d" % len(after - before))
    print("  removed %d" % len(before - after))
    print("  reranked %d" % moved)
    if len(new["belts"]) != len(old["belts"]):
        print("  belts   %s -> %s" % (old["belts"], new["belts"]))

    if a.dry_run:
        print("\n--dry-run: nothing written.")
        return

    blob = json.dumps(new, ensure_ascii=False, separators=(",", ":"))
    if "</script" in blob.lower():
        sys.exit("Refused: parsed data contains a script tag.")
    open(a.app, "w", encoding="utf-8").write(app[:m.start(2)] + blob + app[m.end(2):])
    print("\nWrote %s" % a.app)


if __name__ == "__main__":
    main()
