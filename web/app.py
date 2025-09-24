import os, re, asyncio, httpx
from pathlib import Path
from flask import Flask, request, redirect, url_for, session, render_template, abort, jsonify
from sqlalchemy import select, or_
from brs.models import init_db, SessionLocal, User, Job, Club
from brs.security import hash_password, verify_password, encrypt
from brs.config import SECRET_KEY
from brs.engine import login as brs_login
from bs4 import BeautifulSoup

# --- Directories (point Flask one level up from /web) ---
BASE_DIR = Path(__file__).resolve().parent       # /web
PROJECT_ROOT = BASE_DIR.parent                   # repo root

TEMPLATE_DIR = PROJECT_ROOT / "templates"
STATIC_DIR   = PROJECT_ROOT / "static"

# --- Flask setup ---
app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
    static_url_path="/static"
)
app.secret_key = SECRET_KEY
init_db()

# === Dashboard page (kept as your original PAGE string) ===
PAGE = """
<!doctype html>
<title>BRS Bot</title>
<link rel="stylesheet" href="https://unpkg.com/mvp.css">
<style>
.badge { display:inline-block; padding:.25rem .5rem; border:1px solid #ccc; border-radius:6px; margin:.15rem; }
.badge button { margin-left:.4rem; }
.flex { display:flex; gap:.75rem; align-items:center; flex-wrap:wrap; }
.grid2 { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.5rem; }
.small { font-size:.9rem; color:#555; }
</style>
<main>
  <header>
    <h1>BRS Bot</h1>
    {% if user %}<p>Signed in as {{user.email}} — <a href="{{url_for('logout')}}">Logout</a></p>{% endif %}
  </header>

  {% if not user %}
  <section>
    <h2>Login</h2>
    <form method="post" action="{{url_for('login')}}">
      <input name="email" placeholder="Email" required>
      <input name="password" placeholder="Password" type="password" required>
      <button>Login</button>
    </form>
    <h3>Register</h3>
    <form method="post" action="{{url_for('register')}}">
      <input name="email" placeholder="Email" required>
      <input name="password" placeholder="Password" type="password" required>
      <button>Register</button>
    </form>
  </section>
  {% else %}
  <section>
    <h2>Create watch job</h2>
    <form id="jobform" method="post" action="{{url_for('create_job')}}">
      <div class="grid2">
        <label>
          Club (type to search)
          <input id="club_input" placeholder="Start typing your club…" autocomplete="off" required>
          <input type="hidden" name="club_slug" id="club_slug" required>
          <div id="club_suggest" class="flex"></div>
        </label>
        <label>
          Course ID
          <input name="course_id" placeholder="e.g. 1" required>
        </label>

        <label>
          BRS username / membership #
          <input name="username" id="brs_user" placeholder="10782318" required>
        </label>
        <label>
          BRS password / PIN
          <input name="password" id="brs_pass" placeholder="••••" type="password" required>
        </label>

        <label>
          Target date (YYYY/MM/DD)
          <input name="target_date" id="target_date" placeholder="2025/09/05" required>
        </label>
        <label>
          Current booking (HH:MM)
          <input name="current_time" placeholder="11:57" required>
        </label>

        <label>
          Earliest (HH:MM)
          <input name="earliest" placeholder="08:00" required>
        </label>
        <label>
          Latest (HH:MM)
          <input name="latest" placeholder="10:00" required>
        </label>

        <label>
          Seats needed
          <input name="required_seats" value="4">
        </label>
        <label>
          Poll seconds
          <input name="poll_seconds" value="20">
        </label>

        <label>
          Max minutes (cap)
          <input name="max_minutes" value="120">
        </label>
        <label class="flex">
          <input type="checkbox" name="accept_at_least" checked> Accept at least N seats
        </label>
      </div>

      <hr>
      <h3>Pick players (live search)</h3>
      <p class="small">Search your club members (requires the BRS login above). Click to add up to 4.</p>
      <div class="flex">
        <input id="player_search" placeholder="Type a surname…" style="min-width:260px">
        <button type="button" id="btn_search">Search</button>
        <div id="search_results" class="flex"></div>
      </div>
      <p>Selected:</p>
      <div id="selected_players" class="flex"></div>
      <input type="hidden" name="player_ids_csv" id="player_ids_csv" required>

      <br>
      <button>Create job</button>
    </form>
  </section>

  <section>
    <h2>Your jobs</h2>
    <table>
      <thead><tr><th>ID</th><th>Club</th><th>Date</th><th>Window</th><th>Current</th><th>Status</th><th>Actions</th></tr></thead>
      <tbody>
      {% for j in jobs %}
        <tr>
          <td>{{j.id}}</td>
          <td>{{j.club_slug}}/{{j.course_id}}</td>
          <td>{{j.target_date}}</td>
          <td>{{j.earliest}}–{{j.latest}}</td>
          <td>{{j.current_time}}</td>
          <td>{{j.status}}</td>
          <td>
            <a href="{{url_for('toggle_job', job_id=j.id)}}">{{'Stop' if j.status=='active' else 'Start'}}</a> |
            <a href="{{url_for('delete_job', job_id=j.id)}}" onclick="return confirm('Delete job?')">Delete</a>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </section>
  {% endif %}
</main>

<script>
(function(){
  // Club resolver
  const clubInput = document.getElementById('club_input');
  const clubSlug = document.getElementById('club_slug');
  const sugg = document.getElementById('club_suggest');
  let t=null;

  function clearSugg(){ sugg.innerHTML=''; }
  function setClub(name, slug){
    clubInput.value = name + ' ('+slug+')';
    clubSlug.value = slug;
    clearSugg();
  }
  clubInput?.addEventListener('input', ()=>{
    clubSlug.value = '';
    clearSugg();
    const q = clubInput.value.trim();
    if(t) clearTimeout(t);
    if(q.length < 3) return;
    t = setTimeout(async ()=>{
      const r = await fetch('/api/clubs/search?q='+encodeURIComponent(q));
      const data = await r.json();
      clearSugg();
      (data.results||[]).forEach(({name,slug})=>{
        const b = document.createElement('button');
        b.type='button'; b.textContent = name + ' — ' + slug;
        b.onclick = ()=> setClub(name, slug);
        sugg.appendChild(b);
      });
      if((data.results||[]).length===0){
        sugg.innerHTML = '<span class="small">No matches yet — try another spelling.</span>';
      }
    }, 250);
  });

  // Player selector
  const resBox = document.getElementById('search_results');
  const selBox = document.getElementById('selected_players');
  const idsField = document.getElementById('player_ids_csv');

  function renderSelected(list){
    selBox.innerHTML = '';
    list.forEach(({id,text})=>{
      const b = document.createElement('span');
      b.className = 'badge';
      b.textContent = text + ' ('+id+')';
      const x = document.createElement('button'); x.type='button'; x.textContent='×';
      x.onclick = ()=>{
        const arr = getSelected().filter(p => p.id !== id);
        renderSelected(arr);
        idsField.value = arr.map(p=>p.id).join(',');
        sessionStorage.setItem('sel_players', JSON.stringify(arr));
      };
      b.appendChild(x);
      selBox.appendChild(b);
    });
  }
  function getSelected(){
    try { return JSON.parse(sessionStorage.getItem('sel_players')||'[]'); } catch(e){ return []; }
  }

  document.getElementById('btn_search')?.addEventListener('click', async ()=>{
    resBox.innerHTML = 'Searching…';
    const club = clubSlug.value;
    const user = document.getElementById('brs_user').value;
    const pass = document.getElementById('brs_pass').value;
    const date = document.getElementById('target_date').value || '';
    const q = document.getElementById('player_search').value.trim();
    if(!club || !user || !pass || !q){ resBox.innerHTML = 'Enter club, login and a search term.'; return; }
    const r = await fetch(`/api/players/search?club=${encodeURIComponent(club)}&q=${encodeURIComponent(q)}&date=${encodeURIComponent(date)}`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ username:user, password:pass })
    });
    const data = await r.json();
    resBox.innerHTML = '';
    (data.results||[]).forEach(({id,text})=>{
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = text + ' ('+id+')';
      btn.onclick = ()=>{
        let cur = getSelected();
        if(cur.find(p=>p.id===id)) return;
        if(cur.length>=4){ alert('Max 4 players'); return; }
        cur.push({id,text});
        sessionStorage.setItem('sel_players', JSON.stringify(cur));
        renderSelected(cur);
        idsField.value = cur.map(p=>p.id).join(',');
      };
      resBox.appendChild(btn);
    });
    if((data.results||[]).length===0){ resBox.innerHTML = 'No matches.'; }
  });

  // Restore selection
  renderSelected(getSelected());
  idsField.value = getSelected().map(p=>p.id).join(',');

  // Clear on submit
  document.getElementById('jobform')?.addEventListener('submit', ()=>{
    sessionStorage.removeItem('sel_players');
  });
})();
</script>
"""

# === Helpers ===
def get_user():
    uid = session.get("uid")
    if not uid: return None
    db = SessionLocal()
    try:
        return db.get(User, uid)
    finally:
        db.close()

# === Auth landing page (renders templates/auth.html) ===
@app.get("/auth")
def auth():
    if get_user():
        return redirect(url_for("home"))
    return render_template("auth.html")

# === Home/Dashboard (requires login) ===
@app.get("/")
def home():
    user = get_user()
    if not user:
        return redirect(url_for("auth"))

    jobs = []
    db = SessionLocal()
    try:
        jobs = db.scalars(
            select(Job).where(Job.user_id == user.id).order_by(Job.id.desc())
        ).all()
    finally:
        db.close()
    return render_template_string(PAGE, user=user, jobs=jobs)

# === Auth actions ===
@app.post("/register")
def register():
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.email == email)):
            return "Email already registered", 400
        u = User(email=email, password_hash=hash_password(password))
        db.add(u); db.commit()
        session["uid"] = u.id
    finally:
        db.close()
    return redirect(url_for("home"))

@app.post("/login")
def login():
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    db = SessionLocal()
    try:
        u = db.scalar(select(User).where(User.email == email))
        if not u or not verify_password(u.password_hash, password):
            return "Invalid login", 401
        session["uid"] = u.id
    finally:
        db.close()
    return redirect(url_for("home"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth"))

# === Job management ===
@app.post("/jobs")
def create_job():
    user = get_user()
    if not user: abort(401)
    f = request.form
    pidcsv = f["player_ids_csv"].strip()
    pids = [x for x in pidcsv.split(",") if x.strip()]
    if len(pids) == 0 or len(pids) > 4:
        return "Select between 1 and 4 players", 400
    db = SessionLocal()
    try:
        j = Job(
            user_id=user.id,
            club_slug=f["club_slug"].strip(),
            course_id=f["course_id"].strip(),
            member_username_enc=encrypt(f["username"].strip()),
            member_password_enc=encrypt(f["password"].strip()),
            target_date=f["target_date"].strip(),
            earliest=f["earliest"].strip(),
            latest=f["latest"].strip(),
            current_time=f["current_time"].strip(),
            required_seats=int(f.get("required_seats","4")),
            accept_at_least=("accept_at_least" in f),
            poll_seconds=int(f.get("poll_seconds","20")),
            max_minutes=int(f.get("max_minutes","120")),
            player_ids_csv=pidcsv,
            status="active",
        )
        db.add(j); db.commit()
    finally:
        db.close()
    return redirect(url_for("home"))

@app.get("/jobs/<int:job_id>/toggle")
def toggle_job(job_id):
    user = get_user()
    if not user: abort(401)
    db = SessionLocal()
    try:
        j = db.get(Job, job_id)
        if not j or j.user_id != user.id: abort(404)
        j.status = "stopped" if j.status == "active" else "active"
        db.commit()
    finally:
        db.close()
    return redirect(url_for("home"))

@app.get("/jobs/<int:job_id>/delete")
def delete_job(job_id):
    user = get_user()
    if not user: abort(401)
    db = SessionLocal()
    try:
        j = db.get(Job, job_id)
        if not j or j.user_id != user.id: abort(404)
        db.delete(j); db.commit()
    finally:
        db.close()
    return redirect(url_for("home"))

# === Club resolver API (live probe + cache) ===
def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"(golf( club)?|g.c.|g&cc|g\s*&\s*c|\bgc\b)$", "", s)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _slug_candidates(q: str) -> list[str]:
    q = _norm(q)
    parts = q.split()
    base = ["-".join(parts), "_".join(parts), "".join(parts)]
    base += [ "-".join(p for p in parts if p not in ("golf","club")) ]
    if len(parts) > 2:
        base += [ "-".join(parts[:2]), "-".join(parts[-2:]) ]
    seen, out = set(), []
    for s in base:
        s = s.strip("-_")
        if s and s not in seen:
            out.append(s); seen.add(s)
    return out

async def _probe_slug(slug: str) -> bool:
    url = f"{BASE}/{slug}/login"
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers={"User-Agent": UA})
        return r.status_code in (200, 302)

@app.get("/api/clubs/search")
async def api_clubs_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})
    db = SessionLocal()
    try:
        like = f"%{_norm(q).replace(' ', '%')}%"
        cached = db.scalars(
            select(Club).where(or_(Club.name.ilike(like), Club.slug.ilike(like)))
                        .order_by(Club.name.asc())
        ).all()
        results = [ {"name": c.name, "slug": c.slug} for c in cached ]

        cand_slugs = _slug_candidates(q)
        discovered = []
        for slug in cand_slugs:
            if any(r["slug"] == slug for r in results):
                continue
            ok = await _probe_slug(slug)
            if ok:
                c = Club(name=q, slug=slug, country="UK")
                try:
                    db.add(c); db.commit()
                except Exception:
                    db.rollback()
                discovered.append({"name": q, "slug": slug})
        results += discovered
        unique = {}
        for r in results:
            unique[r["slug"]] = r
        return jsonify({"results": list(unique.values())[:20]})
    finally:
        db.close()

# === Player search API ===
@app.post("/api/players/search")
async def api_players_search():
    club = (request.args.get("club") or "").strip()
    q = (request.args.get("q") or "").strip()
    date = (request.args.get("date") or "").strip()
    body = request.get_json(force=True, silent=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    if not club or not q or not username or not password:
        return jsonify({"results": []})

    timeout = httpx.Timeout(30.0, connect=15.0)
    async with httpx.AsyncClient(base_url=BASE, timeout=timeout) as client:
        # 1) login (reuse engine login for robustness)
        await brs_login(client, club, username, password, base=BASE)

        # 2) discover autocomplete URL by opening a store page
        ymd = (date or "2025/09/05").replace("/","")
        autouri = None
        for hhmm in ("0700","0730","0800","0900","0000"):
            url = f"/{club}/bookings/store/1/{ymd}/{hhmm}"
            r3 = await client.get(url, headers={"User-Agent": UA, "Referer": url})
            if r3.status_code != 200:
                continue
            soup3 = BeautifulSoup(r3.text, "lxml")
            txt = soup3.find("input", attrs={"name": "member_booking_form[player_1_text]"}) or \
                  soup3.find("input", attrs={"data-autocomplete-url": True})
            if txt and txt.get("data-autocomplete-url"):
                autouri = txt.get("data-autocomplete-url")
                if not autouri.startswith("/"):
                    autouri = "/" + autouri
                break

        if not autouri:
            return jsonify({"results": [], "error": "autocomplete url not found"})

        # 3) query autocomplete
        params = {"q": q, "term": q}
        r = await client.get(autouri, params=params, headers={"User-Agent": UA})
        if r.status_code != 200:
            return jsonify({"results": []})
        try:
            data = r.json()
        except Exception:
            data = []

        results = []
        for item in data if isinstance(data, list) else []:
            pid = item.get("id") or item.get("value") or item.get("member_id")
            txt = item.get("text") or item.get("label") or item.get("name")
            if pid and txt:
                results.append({"id": int(pid), "text": txt})
        return jsonify({"results": results[:20]})

# === Optional tiny placeholders for links in auth.html ===
@app.get("/forgot")
def forgot_password():
    return "Password reset instructions coming soon.", 200

@app.get("/terms")
def terms():
    return "Terms of Service placeholder.", 200

@app.get("/privacy")
def privacy():
    return "Privacy Policy placeholder.", 200
