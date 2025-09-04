import asyncio, httpx, random, time, html as htmllib
from bs4 import BeautifulSoup
from urllib.parse import unquote
from datetime import datetime, timedelta

DEFAULT_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
              "Mobile/15E148 Safari/604.1")

def to_minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])

def absolutize(base: str, club: str, path: str) -> str:
    if path.startswith("http"): return path
    if path.startswith("/"):    return base + path
    return f"{base}/{club}/{path}"

class TeeSheetCache:
    def __init__(self, ttl_seconds=20, base="https://members.brsgolf.com"):
        self.ttl = ttl_seconds
        self.base = base
        self._data = {}  # key -> (ts, json)

    async def fetch(self, client: httpx.AsyncClient, club_slug: str, course_id: str, ymd_slash: str):
        key = (club_slug, course_id, ymd_slash)
        now = time.time()
        if key in self._data and (now - self._data[key][0]) < self.ttl:
            return self._data[key][1]
        url = f"{self.base}/{club_slug}/tee-sheet/data/{course_id}/{ymd_slash}"
        r = await client.get(url, headers={"User-Agent": DEFAULT_UA})
        r.raise_for_status()
        data = r.json()
        self._data[key] = (now, data)
        return data

async def login(client: httpx.AsyncClient, club_slug: str, username: str, password: str, base="https://members.brsgolf.com"):
    login_url = f"{base}/{club_slug}/login"
    r = await client.get(login_url, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    form_el = soup.find("form", attrs={"name": True}) or soup.find("form")
    if not form_el: raise RuntimeError("Login form not found")

    data = {}
    for inp in form_el.find_all("input"):
        nm = inp.get("name"); t = (inp.get("type") or "").lower()
        if not nm: continue
        if t in ("checkbox","radio"):
            if inp.has_attr("checked"): data[nm] = inp.get("value","on")
        else:
            data[nm] = inp.get("value","")
    user_keys = ["login_form[username]","login_form_membership_number","login_form_membership","username","membership_number","login[username]","login[membership_number]"]
    pass_keys = ["login_form[password]","login_form_password","password","login[password]"]
    user_field = next((k for k in user_keys if k in data), None)
    pass_field = next((k for k in pass_keys if k in data), None)
    if not user_field:
        cand = form_el.find("input", attrs={"type": ["text","email","tel","number"]})
        if cand: user_field = cand.get("name")
    if not pass_field:
        cand = form_el.find("input", attrs={"type":"password"})
        if cand: pass_field = cand.get("name")
    if not user_field or not pass_field:
        raise RuntimeError("Could not detect login fields")

    data[user_field] = username
    data[pass_field] = password

    action = absolutize(base, club_slug, form_el.get("action") or login_url)
    r2 = await client.post(action, data=data, headers={"User-Agent": DEFAULT_UA}, follow_redirects=True)
    r2.raise_for_status()
    if BeautifulSoup(r2.text, "lxml").find("input", {"type":"password"}):
        raise RuntimeError("Login failed")

def seats_free(tee: dict) -> tuple[int,int]:
    parts = tee.get("participants") or tee.get("players") or []
    total = tee.get("slots") or (len(parts) or 4)
    named = sum(1 for p in parts if (p or {}).get("name"))
    return max(0, total - named), total

def find_candidate_by_free_seats(sheet: dict, earliest: str, latest: str, need: int, accept_at_least=True, debug=False, cap=20):
    times = (sheet or {}).get("times", {})
    e_min, l_min = to_minutes(earliest), to_minutes(latest)
    shown = 0
    for hhmm, obj in sorted(times.items()):
        tmin = to_minutes(hhmm)
        if tmin < e_min or tmin > l_min: continue
        tee = obj.get("tee_time") or {}
        free, total = seats_free(tee)
        match = (free >= need) if accept_at_least else (free == need)
        if debug and shown < cap:
            print(f"[scan] {hhmm} | free {free}/{total} | bookable={bool(tee.get('bookable'))} | {'OK' if match else 'skip'}")
            shown += 1
        if match:
            return hhmm
    return None

async def get_book_url_from_sheet(client: httpx.AsyncClient, club_slug: str, course_id: str, ymd_slash: str, hhmm: str, base="https://members.brsgolf.com"):
    url = f"{base}/{club_slug}/tee-sheet/data/{course_id}/{ymd_slash}"
    r = await client.get(url, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    data = r.json()
    key = f"{hhmm[:2]}:{hhmm[2:]}"
    slot = (data.get("times") or {}).get(key, {})
    tee = (slot or {}).get("tee_time") or {}
    u = tee.get("url") or ""
    if not u: return None
    u = htmllib.unescape(u).replace("\\/","/")
    for _ in range(2): u = unquote(u)
    if not u.startswith("/"): u = "/" + u
    return absolutize(base, club_slug, u)

async def prepare_payload(client: httpx.AsyncClient, book_url: str, player_ids: list[int]):
    r = await client.get(book_url, headers={"User-Agent": DEFAULT_UA, "Referer": book_url})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    form = None
    for f in soup.find_all("form"):
        names = " ".join([inp.get("name","") for inp in f.find_all("input")])
        if "player_1" in names:
            form = f; break
    if not form: raise RuntimeError("Booking form not found on book URL")

    fields = {}
    for inp in form.find_all(["input","select","textarea"]):
        nm = inp.get("name"); t = (inp.get("type") or "").lower()
        if not nm: continue
        if inp.name == "select":
            sel = inp.find("option", selected=True) or inp.find("option")
            fields[nm] = sel.get("value","") if sel else fields.get(nm,"")
        elif t in ("checkbox","radio"):
            if inp.has_attr("checked"): fields[nm] = inp.get("value","on")
            elif nm not in fields: fields[nm] = ""
        else:
            fields[nm] = inp.get("value","")
    for i, pid in enumerate(player_ids, start=1):
        fields[f"member_booking_form[player_{i}]"] = str(pid)
    vkey = "member_booking_form[vendor-tx-code]"
    fields[vkey] = fields.get(vkey) or f"svc-{int(time.time()*1000)}-{random.randint(100000,999999)}"

    action = form.get("action") or book_url
    return action, fields

async def post_form(client: httpx.AsyncClient, post_url: str, fields: dict, referer: str):
    r = await client.post(post_url, data=fields, headers={"User-Agent": DEFAULT_UA, "Referer": referer}, follow_redirects=True)
    if r.status_code not in (200, 302): return False
    return True

async def cancel_booking(client: httpx.AsyncClient, club_slug: str, course_id: str, ymd_slash: str, time_hhmm: str, base="https://members.brsgolf.com"):
    yyyymmdd = ymd_slash.replace("/", "")
    hhmm4 = time_hhmm.replace(":", "")
    url = f"{base}/{club_slug}/bookings/delete/{course_id}/{yyyymmdd}/{hhmm4}"
    r = await client.post(url, headers={"User-Agent": DEFAULT_UA}, follow_redirects=True)
    return r.status_code in (200, 204, 302)

async def verify_booked(client: httpx.AsyncClient, club_slug: str, course_id: str, ymd_slash: str, hhmm4: str, base="https://members.brsgolf.com"):
    url = f"{base}/{club_slug}/tee-sheet/data/{course_id}/{ymd_slash}"
    r = await client.get(url, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    data = r.json()
    key = f"{hhmm4[:2]}:{hhmm4[2:]}"
    slot = (data.get("times") or {}).get(key, {})
    tee = (slot or {}).get("tee_time") or {}
    return (not tee.get("bookable")), [ (p or {}).get("name") for p in (tee.get("players") or tee.get("participants") or []) ]

async def run_swapper_job(cfg: dict, log=print):
    base = "https://members.brsgolf.com"
    timeout = httpx.Timeout(30.0, connect=15.0)
    async with httpx.AsyncClient(base_url=base, timeout=timeout) as client:
        await login(client, cfg["club_slug"], cfg["username"], cfg["password"], base=base)
        log("Logged in ✔")

        cache = TeeSheetCache(ttl_seconds=max(5, int(cfg.get("poll_seconds", 20))))
        deadline = datetime.utcnow() + timedelta(minutes=int(cfg.get("max_minutes", 120)))

        while datetime.utcnow() < deadline:
            sheet = await cache.fetch(client, cfg["club_slug"], cfg["course_id"], cfg["target_date"])
            cand_hhmm = find_candidate_by_free_seats(
                sheet,
                cfg["earliest"], cfg["latest"],
                int(cfg.get("required_seats", 4)),
                accept_at_least=bool(cfg.get("accept_at_least", True)),
                debug=True, cap=25
            )
            if not cand_hhmm:
                await asyncio.sleep(int(cfg.get("poll_seconds", 20))); continue

            log(f"Found candidate by free seats: {cand_hhmm}")
            ok_cancel = await cancel_booking(client, cfg["club_slug"], cfg["course_id"], cfg["target_date"], cfg["current_time"], base=base)
            if not ok_cancel:
                log("Cancel failed; will retry after short sleep.")
                await asyncio.sleep(int(cfg.get("poll_seconds", 20))); continue

            new_hhmm = cand_hhmm
            new_hhmm4 = new_hhmm.replace(":","")

            async def fetch_book_url_retry(target, tries=6, wait=0.5):
                for _ in range(tries):
                    u = await get_book_url_from_sheet(client, cfg["club_slug"], cfg["course_id"], cfg["target_date"], target.replace(":",""), base=base)
                    if u: return u
                    await asyncio.sleep(wait)
                return None

            new_book_url = await fetch_book_url_retry(new_hhmm)
            if not new_book_url:
                log("Could not obtain tokenised book URL; attempting to re-book original.")
                orig_book_url = await fetch_book_url_retry(cfg["current_time"])
                if orig_book_url:
                    post_u, fields = await prepare_payload(client, orig_book_url, cfg["player_ids"])
                    ok_rb = await post_form(client, post_u, fields, orig_book_url)
                    log(f"Re-book original {'OK' if ok_rb else 'failed'}")
                return {"status":"failed", "reason":"no_book_url"}

            post_u, fields = await prepare_payload(client, new_book_url, cfg["player_ids"])
            ok_book = await post_form(client, post_u, fields, new_book_url)
            if ok_book:
                stuck, players = await verify_booked(client, cfg["club_slug"], cfg["course_id"], cfg["target_date"], new_hhmm4, base=base)
                if stuck:
                    log(f"✅ Booked {new_hhmm}. Players: {players}")
                    return {"status":"success", "time": new_hhmm, "players": players}
                else:
                    log("POST ok but slot still bookable — race; trying to re-book original.")

            orig_book_url = await fetch_book_url_retry(cfg["current_time"])
            if orig_book_url:
                post_u, fields = await prepare_payload(client, orig_book_url, cfg["player_ids"])
                ok_rb = await post_form(client, post_u, fields, orig_book_url)
                log(f"Re-book original {'OK' if ok_rb else 'failed'}")

            await asyncio.sleep(int(cfg.get("poll_seconds", 20)))

        return {"status":"expired"}
