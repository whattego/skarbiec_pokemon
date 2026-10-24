#!/usr/bin/env python3
"""
Skarbiec – bot panelu inwestycyjnego kart Pokémon.

Codziennie (GitHub Actions):
  1. pobiera publiczny cennik Cardmarketu (Pokémon: single + sealed) i kurs EUR/PLN z NBP,
  2. odszyfrowuje twój skarbiec (watchlisty + portfel) hasłem z sekretu SKARBIEC_PASSWORD,
  3. dopisuje historię cen śledzonych produktów, wartość portfela i dzienny „zrzut rynku”,
  4. sprawdza warunki alertów i wysyła je na Discord (sekret DISCORD_WEBHOOK),
  5. zapisuje zaszyfrowaną historię (docs/market.enc) i publiczny katalog do wyszukiwarki.

Nie loguje się na Cardmarket i nie wchodzi na jego stronę – czyta tylko publiczne pliki z cenami.
"""
import base64
import gzip
import json
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
VAULT = os.path.join(DOCS, "vault.enc")
MARKET = os.path.join(DOCS, "market.enc")
CATALOG = os.path.join(DOCS, "catalog.json")
EXPANSIONS = os.path.join(DOCS, "expansions.json")
META = os.path.join(DOCS, "meta.json")
SNAPDIR = os.path.join(DOCS, "snap")

CM = "https://downloads.s3.cardmarket.com/productCatalog"
PRICE_URL = f"{CM}/priceGuide/price_guide_6.json"
SINGLES_URL = f"{CM}/productList/products_singles_6.json"
NONSINGLES_URL = f"{CM}/productList/products_nonsingles_6.json"
NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json"
TCGDEX = "https://api.tcgdex.net/v2"

ITER = 310_000
SNAP_MIN_EUR = float(os.environ.get("SNAP_MIN_EUR", "10"))   # dzienny zrzut rynku: produkty z trendem ≥ tej kwoty
DEFAULT_SETTINGS = {
    "drop_alert_pct": 10,        # lista straciła ≥ X% w 7 dni
    "card_drop_alert_pct": 25,   # pozycja spadła ≥ X% od poprzedniego dnia
    "dip_alert_pct": 20,         # pozycja ≥ X% poniżej swojego 90-dniowego maksimum (lub średniej 30 dni)
    "profit_steps": [50, 100, 200, 400],   # alert, gdy pozycja w portfelu zyskała tyle %
    "weekly_summary": True,
    "summary_weekday": 0,        # 0 = poniedziałek
}


# ---------------- szyfrowanie (zgodne z WebCrypto na stronie) ----------------
_keys = {}


def derive(pw, salt):
    k = (pw, salt)
    if k not in _keys:
        _keys[k] = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
    return _keys[k]


def encrypt(obj, pw, salt=None):
    salt = salt or os.urandom(16)
    iv = os.urandom(12)
    data = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())
    ct = AESGCM(derive(pw, salt)).encrypt(iv, data, None)
    b = lambda x: base64.b64encode(x).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITER, "salt": b(salt), "iv": b(iv), "ct": b(ct)}


def decrypt(blob, pw):
    d = lambda k: base64.b64decode(blob[k])
    salt = d("salt")
    data = AESGCM(derive(pw, salt)).decrypt(d("iv"), d("ct"), None)
    return json.loads(gzip.decompress(data)), salt


# ---------------- pomocnicze ----------------
def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj, pretty=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1 if pretty else None, separators=None if pretty else (",", ":"))


def fetch_json(url, env_file=None):
    local = os.environ.get(env_file) if env_file else None
    if local:
        return load_json(local)
    req = urllib.request.Request(url, headers={"User-Agent": "skarbiec-bot/1.0 (private collection tracker)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def num(v):
    try:
        v = float(v)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def eur(x):
    return "—" if x is None else f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def pln(x):
    return "—" if x is None else f"{x:,.0f} zł".replace(",", " ")


def pct(a, b):
    return (a - b) / b * 100 if a is not None and b else None


def fpct(p):
    return "—" if p is None else f"{p:+.1f}%".replace(".", ",")


def tax_free_from(purchase):
    """Art. 10 ust. 1 pkt 8 lit. d PIT: pół roku licząc od końca miesiąca nabycia.
    Bezpiecznie: od 1. dnia 7. miesiąca po miesiącu zakupu."""
    d = date.fromisoformat(purchase)
    m = d.month + 7
    return date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)


def item_key(it):
    return f"{int(it['id'])}{'h' if it.get('holo') else ''}"


# ---------------- katalog i nazwy dodatków ----------------
SEALED_SUFFIXES = [
    " Booster Box Case", " Booster Display Box", " Booster Display", " Booster Box", " Display",
    " Elite Trainer Box", " Booster Bundle", " Build & Battle Box", " Booster Pack", " Booster",
    " Sleeved Booster", " 3-Pack Blister", " Blister", " Collection Box", " Collection",
]


def expansion_names(nonsingles):
    names = {}
    for p in nonsingles:
        n = p.get("name", "")
        for s in SEALED_SUFFIXES:
            if n.endswith(s):
                base = n[: -len(s)].strip(" -:")
                exp = p["idExpansion"]
                if base and (exp not in names or len(base) < len(names[exp])):
                    names[exp] = base
                break
    return names


def tcgdex_expansions(products):
    """Nazwy dodatków z TCGdex: dla każdego zestawu TCGdex bierzemy kartę z idProduct Cardmarketu
    i stąd idExpansion. Wynik w docs/expansions.json – kolejne uruchomienia pytają tylko o nowe zestawy.
    Zwraca (nazwy EN, nazwy JA, dodatki z wariantami) jako {idExpansion: nazwa}."""
    cache = load_json(EXPANSIONS, {}) or {}
    cache.setdefault("en", {})
    cache.setdefault("ja", {})
    cache.setdefault("var", {})
    cache.setdefault("done", {"en": [], "ja": []})
    if os.environ.get("TCGDEX_OFF"):
        return cache["en"], cache["ja"], cache["var"]

    def get(path):
        try:
            return fetch_json(f"{TCGDEX}/{path}")
        except Exception as e:  # noqa: BLE001
            print("TCGdex:", path, e)
            return None

    def set_expansion(lang, sid):
        s = get(f"{lang}/sets/{urllib.parse.quote(sid)}")
        if not s:
            return None  # błąd sieci – spróbujemy przy następnym uruchomieniu
        cards = s.get("cards") or []
        # kilka kart z różnych miejsc zestawu (pierwsze bywają bez ceny)
        picks = [cards[i] for i in sorted({0, len(cards) // 3, len(cards) // 2, len(cards) - 1}) if 0 <= i < len(cards)]
        for c in picks:
            card = get(f"{lang}/cards/{urllib.parse.quote(c['id'])}") or {}
            cm = (card.get("pricing") or {}).get("cardmarket") or {}
            p = products.get(int(cm.get("idProduct") or 0))
            if p:
                # warianty (np. Poké Ball / Master Ball pattern) CM trzyma w osobnych dodatkach
                extra = {products[v]["idExpansion"] for v in
                         (int((d.get("thirdParty") or {}).get("cardmarket") or 0) for d in card.get("variants_detailed") or [])
                         if v in products} - {p["idExpansion"]}
                return sid, p["idExpansion"], s.get("name") or sid, extra
        return sid, None, None, set()

    for lang in ("en", "ja"):
        sets = get(f"{lang}/sets") or []
        todo = [s["id"] for s in sets if s["id"] not in cache["done"][lang]]
        if not todo:
            continue
        print(f"TCGdex {lang}: {len(todo)} nowych zestawów")
        with ThreadPoolExecutor(4) as ex:
            for res in ex.map(lambda sid: set_expansion(lang, sid), todo):
                if not res:
                    continue
                sid, exp, name, extra = res
                cache["done"][lang].append(sid)
                if exp is not None:
                    # kilka zestawów TCGdex może wskazać ten sam dodatek CM (np. Trainer Gallery) – zostaje krótsza nazwa
                    cur = cache[lang].get(str(exp))
                    if not cur or len(name) < len(cur):
                        cache[lang][str(exp)] = name
                    for e in extra:
                        cache["var"].setdefault(str(e), f"{name} – warianty")
    save_json(EXPANSIONS, cache)
    return cache["en"], cache["ja"], cache["var"]


def kind_of(category):
    c = (category or "").lower()
    if "single" in c:
        return "S"
    if "display" in c or "box" in c and "booster" in c:
        return "D"
    if "elite" in c or "etb" in c:
        return "E"
    if "booster" in c:
        return "B"
    return "O"


# ---------------- Discord ----------------
COLORS = {"buy": 0x1BAF7A, "drop": 0xE34948, "info": 0x2A78D6, "profit": 0xEDA100, "tax": 0x6250D6, "warn": 0xEB6834}


def send_discord(alerts, site_url):
    hook = os.environ.get("DISCORD_WEBHOOK")
    if not alerts:
        return
    if not hook:
        print("[brak DISCORD_WEBHOOK – alerty tylko w logu]")
        for a in alerts:
            print(f"  [{a['kind']}] {a['title']}\n    {a['text']}")
        return
    embeds = [{"title": a["title"][:250], "description": a["text"][:3900], "color": COLORS.get(a["kind"], 0x898781),
               **({"url": site_url} if site_url else {})} for a in alerts]
    for i in range(0, len(embeds), 10):
        body = {"username": "Skarbiec", "embeds": embeds[i:i + 10]}
        req = urllib.request.Request(hook, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "skarbiec-bot/1.0"})
        urllib.request.urlopen(req, timeout=30).read()


# ---------------- główna logika ----------------
def main():
    pw = os.environ.get("SKARBIEC_PASSWORD")
    if not pw:
        sys.exit("Brak sekretu SKARBIEC_PASSWORD (to samo hasło, którym logujesz się na stronę).")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    site_url = os.environ.get("SITE_URL") or (f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else "")

    if "--test" in sys.argv:
        send_discord([{"kind": "info", "title": "✅ Skarbiec działa",
                       "text": "Alerty o okazjach, spadkach i zyskach będą przychodzić tutaj."}], site_url)
        print("Wysłano wiadomość testową.")
        return

    vault_blob = load_json(VAULT)
    if not vault_blob:
        sys.exit("Brak docs/vault.enc – najpierw załóż skarbiec na stronie (pierwsze logowanie).")
    vault, _ = decrypt(vault_blob, pw)
    settings = {**DEFAULT_SETTINGS, **vault.get("settings", {})}

    market_blob = load_json(MARKET)
    if market_blob:
        market, msalt = decrypt(market_blob, pw)
    else:
        market, msalt = {"v": 1, "h": {}, "fx": {}, "pv": [], "alerts": [], "state": {}}, None

    guide_raw = fetch_json(PRICE_URL, "CM_PRICE_FILE")
    singles = fetch_json(SINGLES_URL, "CM_SINGLES_FILE")["products"]
    try:
        nonsingles = fetch_json(NONSINGLES_URL, "CM_NONSINGLES_FILE")["products"]
    except Exception as e:  # noqa: BLE001
        print("Nie udało się pobrać listy produktów sealed:", e)
        nonsingles = []
    guide = {int(g["idProduct"]): g for g in guide_raw["priceGuides"]}
    products = {int(p["idProduct"]): p for p in singles + nonsingles}
    day = os.environ.get("CM_DAY") or guide_raw.get("createdAt", "")[:10] or datetime.now(timezone.utc).date().isoformat()

    # kurs EUR/PLN (NBP, tabela A)
    fx = None
    if os.environ.get("FX_EURPLN"):
        fx = float(os.environ["FX_EURPLN"])
    else:
        try:
            fx = float(fetch_json(NBP_URL)["rates"][0]["mid"])
        except Exception as e:  # noqa: BLE001
            print("NBP niedostępne:", e)
    if fx is None:
        fx = market["fx"][max(market["fx"])] if market["fx"] else 4.3
    market["fx"][day] = fx

    # --- publiczny katalog (wyszukiwarka) i dzienny zrzut rynku ---
    # nazwy dodatków: TCGdex EN > nazwy z sealed Cardmarketu > TCGdex JA > warianty z TCGdex
    tcg_en, tcg_ja, tcg_var = tcgdex_expansions(products)
    exps = {int(k): v for k, v in tcg_var.items()}
    exps.update({int(k): v for k, v in tcg_ja.items()})
    exps.update(expansion_names(nonsingles))
    exps.update({int(k): v for k, v in tcg_en.items()})
    cats = []
    rows = []
    for pid, p in products.items():
        g = guide.get(pid)
        if not g:
            continue
        cat = p.get("categoryName", "")
        if cat not in cats:
            cats.append(cat)
        rows.append([pid, p.get("name", ""), cats.index(cat), p.get("idExpansion"),
                     num(g.get("trend")), num(g.get("low")), num(g.get("avg1")), num(g.get("avg7")), num(g.get("avg30")),
                     num(g.get("trend-holo"))])
    save_json(CATALOG, {"day": day, "fx": fx, "cats": cats, "kinds": [kind_of(c) for c in cats],
                        "exp": {str(k): v for k, v in exps.items()}, "p": rows})
    snap_path = os.path.join(SNAPDIR, f"{day}.json")
    if not os.path.exists(snap_path):
        save_json(snap_path, {str(r[0]): r[4] for r in rows if r[4] and r[4] >= SNAP_MIN_EUR})
    snap_days = sorted(f[:-5] for f in os.listdir(SNAPDIR) if f.endswith(".json") and f[0].isdigit())
    save_json(os.path.join(SNAPDIR, "index.json"), snap_days)

    # --- historia śledzonych pozycji ---
    def price_of(key):
        pid, holo = int(key.rstrip("h")), key.endswith("h")
        g = guide.get(pid)
        if not g:
            return None
        if holo:
            return [num(g.get("trend-holo")), num(g.get("low-holo")), num(g.get("avg7-holo")), num(g.get("avg30-holo")), num(g.get("avg1-holo"))]
        return [num(g.get("trend")), num(g.get("low")), num(g.get("avg7")), num(g.get("avg30")), num(g.get("avg1"))]

    tracked = set()
    for wl in vault.get("watchlists", []):
        for it in wl.get("items", []):
            tracked.add(item_key(it))
    for h in vault.get("portfolio", []):
        if not h.get("sold"):
            tracked.add(item_key(h))
    hist = market["h"]
    fresh = set()   # klucze, które dziś dostały nowy pomiar (do alertów dzień-do-dnia)
    for key in tracked:
        pr = price_of(key)
        if not pr or pr[0] is None:
            continue
        series = hist.setdefault(key, [])
        if series and series[-1][0] == day:
            series[-1] = [day] + pr
        else:
            series.append([day] + pr)
            fresh.add(key)
        del series[:-1500]

    def trend_on(key, d):
        for row in reversed(hist.get(key, [])):
            if row[0] <= d:
                return row[1] if row[0] == d else None
        return None

    def series_sum(items, metric_idx=1):
        """Suma listy po dniach – tylko dni, w których znamy cenę każdej pozycji."""
        keys = [item_key(i) for i in items]
        qty = {item_key(i): i.get("qty", 1) for i in items}
        if not keys:
            return []
        days = sorted({r[0] for k in keys for r in hist.get(k, [])})
        out = []
        for d in days:
            tot = 0
            for k in keys:
                row = next((r for r in hist.get(k, []) if r[0] == d), None)
                if not row or row[metric_idx] is None:
                    break
                tot += row[metric_idx] * qty[k]
            else:
                out.append((d, tot))
        return out

    st = market["state"]
    alerts = []
    today = date.fromisoformat(day)

    def alert(kind, title, text):
        alerts.append({"kind": kind, "title": title, "text": text})

    def name_of(it):
        return it.get("name") or products.get(int(it["id"]), {}).get("name", f"#{it['id']}")

    # --- alerty watchlist ---
    for wl in vault.get("watchlists", []):
        items = wl.get("items", [])
        if not items:
            continue
        wid = wl["id"]
        ser = series_sum(items)
        if not ser or ser[-1][0] != day:
            missing = [name_of(i) for i in items if trend_on(item_key(i), day) is None]
            if missing and not st.get(f"wl:{wid}:miss") == day:
                alert("warn", f"⚠️ {wl['name']}: brak ceny dla {len(missing)} pozycji", ", ".join(missing[:8]))
                st[f"wl:{wid}:miss"] = day
        else:
            now = ser[-1][1]
            target = wl.get("target_eur")
            # metric == "komplet": próg to komplet EN/NM z wysyłką – sprawdza go rozszerzenie Chrome (auto-koszyk + Discord),
            # bot zna tylko trend (same karty, wszystkie języki), więc tu by alarmował fałszywie
            if target and wl.get("metric") != "komplet":
                below = now <= float(target)
                if below and not st.get(f"wl:{wid}:below"):
                    alert("buy", f"🔥 OKAZJA: {wl['name']} poniżej progu",
                          f"Suma trendu **{eur(now)}** ≤ próg {eur(float(target))} (≈ {pln(now * fx)}).\n"
                          "Sprawdź konkretne oferty i stan kart przed zakupem.")
                elif not below and st.get(f"wl:{wid}:below"):
                    alert("info", f"↗️ {wl['name']} wróciło powyżej progu", f"Suma trendu {eur(now)} > {eur(float(target))}.")
                st[f"wl:{wid}:below"] = below
            week = [v for d, v in ser if d <= (today - timedelta(days=7)).isoformat()]
            if week:
                ch = pct(now, week[-1])
                last = st.get(f"wl:{wid}:drop")
                if ch is not None and ch <= -settings["drop_alert_pct"] and (not last or (today - date.fromisoformat(last)).days >= 3):
                    movers = []
                    for it in items:
                        k = item_key(it)
                        old = [r[1] for r in hist.get(k, []) if r[0] <= (today - timedelta(days=7)).isoformat() and r[1]]
                        cur = trend_on(k, day)
                        if old and cur:
                            movers.append((pct(cur, old[-1]), name_of(it), old[-1], cur))
                    movers.sort()
                    alert("drop", f"📉 {wl['name']}: {fpct(ch)} w 7 dni",
                          f"{eur(week[-1])} → **{eur(now)}**\n" + "\n".join(f"• {n}: {eur(o)} → {eur(c)} ({fpct(p)})" for p, n, o, c in movers[:6]))
                    st[f"wl:{wid}:drop"] = day

        for it in items:
            k = item_key(it)
            rows_k = hist.get(k, [])
            cur = trend_on(k, day)
            if not cur:
                continue
            nm = name_of(it)
            # dzień do dnia
            if k in fresh and len(rows_k) >= 2 and rows_k[-2][1]:
                ch = pct(cur, rows_k[-2][1])
                if ch is not None and ch <= -settings["card_drop_alert_pct"]:
                    alert("drop", f"🔎 {nm}: {fpct(ch)} od poprzedniego dnia", f"{eur(rows_k[-2][1])} → **{eur(cur)}** · lista: {wl['name']}")
            # cena docelowa pozycji
            bb = it.get("buy_below")
            if bb:
                below = cur <= float(bb)
                sk = f"it:{wid}:{k}:bb"
                if below and not st.get(sk):
                    low = rows_k[-1][2] if rows_k else None
                    alert("buy", f"🎯 {nm} poniżej twojej ceny", f"Trend **{eur(cur)}** ≤ {eur(float(bb))} · najtańsza oferta (dowolny język/stan): {eur(low)} · lista: {wl['name']}")
                st[sk] = below
            # spadek względem 90-dniowego maksimum / średniej 30 dni
            ref = [r[1] for r in rows_k if r[0] >= (today - timedelta(days=90)).isoformat() and r[1]]
            avg30 = rows_k[-1][4] if rows_k else None
            peak = max(ref + ([avg30] if avg30 else []))
            dd = pct(cur, peak)
            sk = f"it:{k}:dip"
            last = st.get(sk)
            if dd is not None and dd <= -settings["dip_alert_pct"] and (not last or (today - date.fromisoformat(last)).days >= 14):
                alert("buy", f"💸 {nm}: {fpct(dd)} od szczytu z 90 dni",
                      f"Teraz **{eur(cur)}**, szczyt {eur(peak)}. Możliwy moment na zakup – sprawdź, czy to nie efekt dodruku. Lista: {wl['name']}")
                st[sk] = day

    # --- portfel ---
    value_pln = cost_pln = 0.0
    priced = True
    for h in vault.get("portfolio", []):
        if h.get("sold"):
            continue
        k = item_key(h)
        cur = trend_on(k, day)
        qty = h.get("qty", 1)
        cost = float(h.get("cost_pln") or 0)
        cost_pln += cost
        if cur is None:
            priced = False
            continue
        val = cur * qty * fx
        value_pln += val
        gain = pct(val, cost) if cost else None
        nm = name_of(h)
        if gain is not None:
            done = st.get(f"pf:{h['uid']}:gain", 0)
            steps = [s for s in settings["profit_steps"] if gain >= s and s > done]
            if steps:
                alert("profit", f"💰 {nm}: {fpct(gain)} zysku",
                      f"Wartość wg trendu {pln(val)} przy koszcie {pln(cost)} ({qty} szt.). Rozważ sprzedaż części i odzyskanie kosztu.")
                st[f"pf:{h['uid']}:gain"] = max(steps)
        if h.get("date"):
            free = tax_free_from(h["date"])
            if today >= free and not st.get(f"pf:{h['uid']}:tax"):
                alert("tax", f"🧾 {nm}: od dziś sprzedaż bez PIT",
                      f"Minęło pół roku od końca miesiąca zakupu ({h['date']}). Dotyczy sprzedaży prywatnej (nie w ramach działalności).")
                st[f"pf:{h['uid']}:tax"] = True
    if vault.get("portfolio"):
        pv = market["pv"]
        entry = [day, round(value_pln, 2), round(cost_pln, 2), priced]
        if pv and pv[-1][0] == day:
            pv[-1] = entry
        else:
            pv.append(entry)

    # --- podsumowanie tygodnia ---
    if settings.get("weekly_summary") and today.weekday() == int(settings.get("summary_weekday", 0)) and st.get("summary") != day:
        lines = []
        if vault.get("portfolio"):
            pv = market["pv"]
            wk = [p for p in pv if p[0] <= (today - timedelta(days=7)).isoformat()]
            lines.append(f"**Portfel:** {pln(value_pln)} (koszt {pln(cost_pln)}, {fpct(pct(value_pln, cost_pln))})" +
                         (f" · 7 dni {fpct(pct(value_pln, wk[-1][1]))}" if wk else ""))
        for wl in vault.get("watchlists", []):
            ser = series_sum(wl.get("items", []))
            if ser:
                wk = [v for d, v in ser if d <= (today - timedelta(days=7)).isoformat()]
                peak = max(v for _, v in ser)
                lines.append(f"**{wl['name']}:** {eur(ser[-1][1])}" + (f" · 7 dni {fpct(pct(ser[-1][1], wk[-1]))}" if wk else "") +
                             f" · od szczytu {fpct(pct(ser[-1][1], peak))}")
        if lines:
            alert("info", f"📊 Podsumowanie tygodnia ({day})", "\n".join(lines) + f"\nKurs EUR/PLN: {fx:.4f}".replace(".", ","))
        st["summary"] = day

    for a in alerts:
        market["alerts"].append({"d": day, **a})
    market["alerts"] = market["alerts"][-400:]
    market["day"] = day
    market["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    save_json(MARKET, encrypt(market, pw, msalt))
    save_json(META, {"day": day, "fx": fx, "updated": market["updated"], "tracked": len(tracked),
                     "snap_min_eur": SNAP_MIN_EUR}, pretty=True)
    print(f"Dane z {day} · EUR/PLN {fx} · śledzone pozycje: {len(tracked)} · alerty: {len(alerts)}")
    if "--no-notify" not in sys.argv:
        send_discord(alerts, site_url)


if __name__ == "__main__":
    main()
