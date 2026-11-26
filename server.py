#!/usr/bin/env python3
"""Family Race - a multiplayer version of the Training Race game (no StableKing, no real horses).
Players join a room with a code, the host picks the distance (5-24 furlongs) and how many AI horses join.
Every player writes ONE training: exactly `distance` whole numbers that add up to 100. Plans stay hidden until the race starts.
Race rule (same as the tool): in every furlong the horse with the HIGHER number wins it (rank 0 = best);
ties are broken at random (equal speeds, no jockeys). Rank points are added over all furlongs: the LOWEST total wins.
No outside libraries: python3 server.py   (uses the PORT environment variable, default 8000).
"""
import json, os, random, secrets, string, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_pool.json"), encoding="utf8") as _f:
        AI_POOL = {int(k): v for k, v in json.load(_f).items()}
except Exception:
    AI_POOL = {}
ROOMS = {}
MAX_ROOMS = 300
ROOM_TTL = 6 * 3600
MAX_PLAYERS = 12
MAX_AI = 8
MAX_BODY = 20000
AI_NAMES = ["Thunder Bolt", "Silver Arrow", "Desert Wind", "Night Rider", "Golden Gate", "Storm Chaser", "Red Comet",
            "Blue Lagoon", "Iron Duke", "Lucky Star", "Wild Flame", "Misty Lane", "Royal Quest", "Shadow Dancer"]



HORSE_COLORS = ["#d62828", "#1d6fb8", "#2a9d3f", "#f4a300", "#8e44ad", "#00a6a6", "#e75480", "#7a5230", "#455a64", "#9acd32", "#ff7f50", "#3f51b5"]
JOCKEYS = ["A. Rider", "B. Swift", "C. Morgan", "D. Patel", "E. Novak", "F. Ortiz", "G. Lindqvist", "H. Okafor", "I. Tanaka", "J. Silva"]
STYLES = ["front runner", "stalker", "closer", "even"]


def make_speeds(D, rnd, style=None):
    """24 speed values (like the StableKing horse page): higher = faster on that furlong. Used only to break ties in training."""
    style = style or rnd.choice(STYLES)
    base = rnd.randint(95, 125)
    out = []
    for f in range(24):
        t = f / 23.0
        shape = {"front runner": 22 * (1 - t) - 8, "stalker": 14 * (1 - abs(2 * t - 1)) - 4, "closer": 22 * t - 12, "even": 0}[style]
        out.append(int(max(60, min(160, base + shape + rnd.gauss(0, 7)))))
    return style, out


def make_horse(name, rnd, color):
    style, sp = make_speeds(24, rnd)
    j = rnd.choice(JOCKEYS)
    return dict(name=name, color=color, style=style, speeds=sp, jockey=dict(name=j, speeds=make_speeds(24, rnd, "even")[1]))


# ---------- race logic (pure functions, easy to test) ----------
def valid_plan(plan, D):
    return (isinstance(plan, list) and len(plan) == D and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 100 for x in plan)
            and sum(plan) == 100)


def to100(weights):
    """float weights -> whole numbers that add up to exactly 100 (largest remainder)."""
    s = sum(weights) or 1.0
    q = [w * 100.0 / s for w in weights]
    r = [int(x) for x in q]
    for i in sorted(range(len(q)), key=lambda i: -(q[i] - r[i]))[:100 - sum(r)]:
        r[i] += 1
    return r


def ai_plan(D, rnd):
    """a random AI training in one of several styles that real stables use."""
    style = rnd.choice(["flat", "levels", "spikes", "equal", "front", "back", "blocks"])
    if style == "flat":
        w = [rnd.uniform(0.7, 1.3) for _ in range(D)]
    elif style == "levels":
        lv = [rnd.uniform(0.3, 2.2) for _ in range(3)]
        w = [rnd.choice(lv) for _ in range(D)]
    elif style == "spikes":
        w = [rnd.uniform(0.4, 1.0) for _ in range(D)]
        for f in rnd.sample(range(D), min(D, rnd.randint(2, 4))):
            w[f] = rnd.uniform(2.5, 4.0)
    elif style == "equal":
        W = D // 2 + 1
        on = set(rnd.sample(range(D), W))
        w = [1.0 if f in on else 0.0 for f in range(D)]
    elif style == "front":
        w = [1.6 - 1.2 * f / max(1, D - 1) + rnd.uniform(-.2, .2) for f in range(D)]
    elif style == "back":
        w = [0.4 + 1.2 * f / max(1, D - 1) + rnd.uniform(-.2, .2) for f in range(D)]
    else:  # blocks: a heavy block and a light block
        a = rnd.randint(0, max(0, D - 3)); b = min(D, a + rnd.randint(2, max(2, D // 2)))
        w = [2.0 if a <= f < b else 0.5 for f in range(D)]
    w = [max(0.0, x) for x in w]
    if sum(w) <= 0:
        w = [1.0] * D
    return to100(w)


def simulate(D, entries, rnd):
    """entries: list of dicts(name, plan, ai, owner, color, style, speeds, jockey). Per furlong: MORE training wins; with EQUAL
    training horse speed + jockey speed decides; if that is equal too, random. Rank 0 = best. Lowest total rank points wins."""
    n = len(entries)
    ranks = [[0] * D for _ in range(n)]
    how = [[""] * D for _ in range(n)]   # "s" = the place was decided by speed after equal training, "r" = random
    for f in range(D):
        tr = [e["plan"][f] for e in entries]
        eff = [e["speeds"][f] + e["jockey"]["speeds"][f] for e in entries]
        order = sorted(range(n), key=lambda i: (-tr[i], -eff[i], rnd.random()))
        for r, i in enumerate(order):
            ranks[i][f] = r
            same = [j for j in range(n) if j != i and tr[j] == tr[i]]
            if same:
                how[i][f] = "r" if any(eff[j] == eff[i] for j in same) else "s"
    totals = [sum(r) for r in ranks]
    order = sorted(range(n), key=lambda i: (totals[i], rnd.random()))
    pos = [0] * n
    for p, i in enumerate(order):
        pos[i] = p + 1
    tie_top = sum(1 for t in totals if t == min(totals)) > 1
    horses = []
    for i, e in enumerate(entries):
        horses.append(dict(stable=e.get("stable", ""), real=e.get("real", False), form=e.get("form", ""), name=e["name"], plan=e["plan"], ai=e["ai"], owner=e["owner"], color=e["color"], style=e["style"],
                           jockey=e["jockey"]["name"], speeds=e["speeds"][:D], jspeeds=e["jockey"]["speeds"][:D],
                           ranks=ranks[i], how=how[i], total=totals[i], position=pos[i]))
    horses.sort(key=lambda h: h["position"])
    return dict(distance=D, horses=horses, tie_for_win=tie_top)


# ---------- rooms ----------
def code_new():
    while True:
        c = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4))
        if c not in ROOMS:
            return c


def purge():
    now = time.time()
    for c in [c for c, r in ROOMS.items() if now - r["touched"] > ROOM_TTL]:
        del ROOMS[c]


def clean_name(s):
    s = " ".join(str(s or "").split())[:20]
    return s


def room_state(room, token):
    me = next((p for p in room["players"] if p["token"] == token), None)
    st = dict(code=room["code"], phase=room["phase"], distance=room["distance"], ai=room["ai"], round=room["round"],
              host=bool(me and me["token"] == room["host"]), you=me["name"] if me else None,
              players=[dict(name=p["name"], horse=p["horse"]["name"], color=p["horse"]["color"], ready=p["plan"] is not None, host=p["token"] == room["host"]) for p in room["players"]],
              your_plan=me["plan"] if me else None, max_ai=MAX_AI,
              your_horse=dict(name=me["horse"]["name"], color=me["horse"]["color"], style=me["horse"]["style"], speeds=me["horse"]["speeds"][:room["distance"]],
                              jockey=me["horse"]["jockey"]["name"], jspeeds=me["horse"]["jockey"]["speeds"][:room["distance"]]) if me else None)
    if room["phase"] == "lobby":
        ensure_ai(room)
        st["ai_field"] = [dict(name=e["name"], stable=e["stable"], real=e["real"], plan=e["plan"], style=e["style"], jockey=e["jockey"]["name"]) for e in room["ai_field"]]
    lt = room.get("last")
    if lt and room["phase"] == "lobby":
        st["last"] = dict(distance=lt["distance"], horses=[dict(name=h["name"], stable=h["stable"], ai=h["ai"], position=h["position"], total=h["total"],
                          plan=h["plan"] if (h["ai"] or (me and h["owner"] == me["name"])) else None, you=bool(me and not h["ai"] and h["owner"] == me["name"])) for h in lt["horses"]])
        st["your_last"] = me.get("last_plan") if me else None
    if room["phase"] == "done":
        R = room["result"]
        hs = []
        for h in R["horses"]:
            c = dict(h)
            c["savg"] = round(sum(h["speeds"]) / max(1, len(h["speeds"])))
            c["javg"] = round(sum(h["jspeeds"]) / max(1, len(h["jspeeds"])))
            if h["ai"]:                                          # AI trainings are shown to everybody; their speeds stay hidden
                c["speeds"], c["jspeeds"] = None, None
            elif not me or h["owner"] != me["name"]:             # players see only their OWN training and speeds
                c["plan"], c["speeds"], c["jspeeds"] = None, None, None
            hs.append(c)
        st["result"] = dict(R, horses=hs)
        rc = room.get("rc")
        if rc:
            st["rc"] = dict(state=rc["state"], speed=rc["speed"], replay=rc["replay"], frame=frame_now(rc), server_time=time.time(), fps=1000.0 / (100 + 5 * rc["n"]))
    return st


def frame_now(rc):
    if rc["state"] == "play":
        return rc["base_frame"] + (time.time() - rc["base_t"]) * (1000.0 / (100 + 5 * rc["n"])) * rc["speed"]
    return rc["base_frame"]


def draw_ai(room, rnd=None):
    """AI opponents are drawn in the lobby so every player can see their trainings BEFORE the race and adjust."""
    rnd = rnd or random.Random(secrets.randbits(64))
    D = room["distance"]
    used = {p["horse"]["name"].lower() for p in room["players"]}
    cand = [r for r in AI_POOL.get(D, []) if r[0].lower() not in used and len(r[2]) == D and sum(r[2]) == 100]
    rnd.shuffle(cand)
    field = []
    for k in range(room["ai"]):
        if k < len(cand):
            nm, stable, plan, real = cand[k][0], cand[k][1], list(cand[k][2]), True
        else:
            free = [x for x in AI_NAMES if x.lower() not in used]
            nm = rnd.choice(free) if free else "AI %d" % (k + 1)
            stable, plan, real = "", ai_plan(D, rnd), False
        used.add(nm.lower())
        h = make_horse(nm, rnd, HORSE_COLORS[k % len(HORSE_COLORS)])
        field.append(dict(name=nm, plan=plan, ai=True, owner="AI", stable=stable, real=real, color=h["color"], style=h["style"], speeds=h["speeds"], jockey=h["jockey"]))
    room["ai_field"], room["ai_key"] = field, (D, room["ai"])


def ensure_ai(room):
    names = {p["horse"]["name"].lower() for p in room["players"]}
    f = room.get("ai_field")
    if f is None or room.get("ai_key") != (room["distance"], room["ai"]) or any(e["name"].lower() in names for e in f):
        draw_ai(room)


class Err(Exception):
    pass


def need_room(d):
    room = ROOMS.get(str(d.get("code", "")).upper())
    if not room:
        raise Err("Room not found. Check the code (rooms close after 6 hours).")
    room["touched"] = time.time()
    return room


def need_player(room, d):
    p = next((p for p in room["players"] if p["token"] == d.get("token")), None)
    if not p:
        raise Err("You are not in this room.")
    return p


def api(path, d):
    if path == "/api/create":
        name = clean_name(d.get("name"))
        if not name:
            raise Err("Write your name first.")
        purge()
        if len(ROOMS) >= MAX_ROOMS:
            raise Err("Too many rooms right now. Try again later.")
        tok = secrets.token_hex(12)
        c = code_new()
        hn = clean_name(d.get("horse")) or (name + "'s horse")
        ROOMS[c] = dict(code=c, created=time.time(), touched=time.time(), host=tok, distance=12, ai=2, phase="lobby", round=1, result=None,
                        players=[dict(name=name, token=tok, plan=None, horse=make_horse(hn, random.Random(secrets.randbits(64)), HORSE_COLORS[0]))])
        return dict(code=c, token=tok)
    room = need_room(d)
    if path == "/api/join":
        name = clean_name(d.get("name"))
        if not name:
            raise Err("Write your name first.")
        old = next((p for p in room["players"] if p["name"].lower() == name.lower()), None)
        if old:
            raise Err("That name is taken in this room. Use another name.")
        if room["phase"] != "lobby":
            raise Err("The race already started. Wait for the next round, then join.")
        if len(room["players"]) >= MAX_PLAYERS:
            raise Err("The room is full.")
        tok = secrets.token_hex(12)
        hn = clean_name(d.get("horse")) or (name + "'s horse")
        if any(p["horse"]["name"].lower() == hn.lower() for p in room["players"]):
            raise Err("A horse with that name is already in this room. Use another horse name.")
        room["players"].append(dict(name=name, token=tok, plan=None, horse=make_horse(hn, random.Random(secrets.randbits(64)), HORSE_COLORS[len(room["players"]) % len(HORSE_COLORS)])))
        return dict(code=room["code"], token=tok)
    if path == "/api/state":
        return room_state(room, d.get("token"))
    me = need_player(room, d)
    host = me["token"] == room["host"]
    if path == "/api/settings":
        if not host:
            raise Err("Only the host can change the race.")
        if room["phase"] != "lobby":
            raise Err("The race is already finished. Press Next round first.")
        D = int(d.get("distance", room["distance"]))
        ai = int(d.get("ai", room["ai"]))
        if not 5 <= D <= 24:
            raise Err("Distance must be 5 to 24 furlongs.")
        if not 0 <= ai <= MAX_AI:
            raise Err("AI horses: 0 to %d." % MAX_AI)
        if D != room["distance"]:
            for p in room["players"]:
                p["plan"] = None
        room["distance"], room["ai"] = D, ai
        return room_state(room, me["token"])
    if path == "/api/plan":
        if room["phase"] != "lobby":
            raise Err("The race already started.")
        plan = d.get("plan")
        if not valid_plan(plan, room["distance"]):
            raise Err("A training needs exactly %d whole numbers that add up to 100." % room["distance"])
        me["plan"] = plan
        return room_state(room, me["token"])
    if path == "/api/start":
        if not host:
            raise Err("Only the host can start the race.")
        if room["phase"] != "lobby":
            raise Err("Already started.")
        if any(p["plan"] is None for p in room["players"]):
            raise Err("Waiting for: " + ", ".join(p["name"] for p in room["players"] if p["plan"] is None))
        if len(room["players"]) + room["ai"] < 2:
            raise Err("Add at least one AI horse or wait for another player.")
        rnd = random.Random(secrets.randbits(64))
        names = rnd.sample(AI_NAMES, min(room["ai"], len(AI_NAMES))) + ["AI %d" % (i + 1) for i in range(max(0, room["ai"] - len(AI_NAMES)))]
        entries = [dict(name=p["horse"]["name"], plan=p["plan"], ai=False, owner=p["name"], color=p["horse"]["color"], style=p["horse"]["style"],
                        speeds=p["horse"]["speeds"], jockey=p["horse"]["jockey"],
                        form=" ".join(str(x) for x in reversed(room.get("form", {}).get(p["horse"]["name"].lower(), [])[-8:]))) for p in room["players"]]
        ensure_ai(room)
        for k, e in enumerate(room["ai_field"]):
            entries.append(dict(e, color=HORSE_COLORS[(len(room["players"]) + k) % len(HORSE_COLORS)]))
        room["result"] = simulate(room["distance"], entries, rnd)
        fm = room.setdefault("form", {})
        for hz in room["result"]["horses"]:
            if not hz["ai"]:
                fm.setdefault(hz["name"].lower(), []).append(hz["position"])
        room["phase"] = "done"
        room["rc"] = dict(state="card", speed=1.0, base_frame=0.0, base_t=time.time(), replay=0, n=len(entries))
        return room_state(room, me["token"])
    if path == "/api/race":
        if not host:
            raise Err("Only the host controls the race.")
        rc = room.get("rc")
        if room["phase"] != "done" or not rc:
            raise Err("No race to control.")
        a = str(d.get("action", ""))
        now = time.time()
        cur = frame_now(rc)
        if a == "go" and rc["state"] == "card":
            rc.update(state="play", base_frame=0.0, base_t=now)
        elif a == "pause" and rc["state"] == "play":
            rc.update(state="pause", base_frame=cur)
        elif a == "resume" and rc["state"] == "pause":
            rc.update(state="play", base_t=now)
        elif a == "speed":
            v = float(d.get("speed", 1))
            if v not in (0.25, 0.5, 1.0, 2.0, 4.0, 10.0):
                raise Err("Bad speed.")
            rc.update(base_frame=cur, base_t=now, speed=v)
        elif a == "skip" and rc["state"] != "card":
            rc.update(state="pause", base_frame=1e6)
        elif a == "replay":
            rc.update(state="play", base_frame=0.0, base_t=now, replay=rc["replay"] + 1)
        return room_state(room, me["token"])
    if path == "/api/next":
        if not host:
            raise Err("Only the host can start the next round.")
        R = room["result"]
        room["last"] = dict(distance=R["distance"], horses=[dict(name=h["name"], stable=h.get("stable", ""), ai=h["ai"], owner=h["owner"], position=h["position"], total=h["total"], plan=h["plan"]) for h in R["horses"]])
        for p in room["players"]:
            p["last_plan"] = p["plan"]
        room["phase"], room["result"], room["rc"], room["ai_field"] = "lobby", None, None, None
        room["round"] += 1
        for p in room["players"]:
            p["plan"] = None
        return room_state(room, me["token"])
    if path == "/api/leave":
        room["players"] = [p for p in room["players"] if p is not me]
        if not room["players"]:
            del ROOMS[room["code"]]
        elif host:
            room["host"] = room["players"][0]["token"]
        return dict(ok=True)
    raise Err("Unknown request.")


class H(BaseHTTPRequestHandler):
    server_version = "FamilyRace/1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", cache="no-store"):
        b = body if isinstance(body, bytes) else body.encode("utf8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(b)

    def _api(self, path, d):
        try:
            with LOCK:
                out = api(path, d)
            self._send(200, json.dumps(out))
        except Err as e:
            self._send(400, json.dumps(dict(error=str(e))))
        except (ValueError, TypeError, KeyError):
            self._send(400, json.dumps(dict(error="Bad request.")))

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if u.path.startswith("/assets/"):
            root = os.path.realpath(os.path.join(HERE, "assets"))
            fp = os.path.realpath(os.path.join(HERE, u.path.lstrip("/")))
            ext = os.path.splitext(fp)[1].lower()
            ct = {".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg"}.get(ext)
            if fp.startswith(root + os.sep) and ct and os.path.isfile(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), ct, "public, max-age=86400")
            return self._send(404, json.dumps(dict(error="Not found.")))
        if u.path == "/health":
            return self._send(200, "ok", "text/plain")
        if u.path == "/api/state":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            return self._api(u.path, q)
        self._send(404, json.dumps(dict(error="Not found.")))

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > MAX_BODY:
                return self._send(413, json.dumps(dict(error="Too big.")))
            d = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(d, dict):
                raise ValueError
        except ValueError:
            return self._send(400, json.dumps(dict(error="Bad request.")))
        self._api(u.path, d)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print("Family Race on http://0.0.0.0:%d" % port, flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
