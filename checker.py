#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitch Drops Radar - checador (multi-fonte).

Este script NAO toca a Twitch: so consome fontes de terceiros. Roda em qualquer lugar.

DROPS (itens de jogo), fundidos por id + chave difusa (jogo+dia de inicio):
  1) sunkwi  https://twitch-drops-api.sunkwi.com/v2/drops  -> ATIVOS + allow.channels (aberto/fechado)
  2) fenris  https://twitch-drops.fenrisapps.com/campaigns -> EM BREVE + ativos (payload SSR/RSC)
  3) twitchdrops.app                                       -> preenche lacunas (pega o que 1/2 perdem),
     traz data-allchannels (respeita "so aberto") e nomes/imagens de recompensa.
BADGES (evento de categoria, coisa diferente de drop de item):
  4) streamdatabase.com/events -> badges CHEGANDO (secao propria no site)

Regras (pedido do dono):
  - So ABERTO a qualquer streamer. Fechado (canais especificos) descartado.
  - EXPIRED fora. UPCOMING no topo.
  - reward_type: "game" (item de jogo) vs "platform" (badge/emote/etc, filtravel no site)
"""
import json
import os
import re
import datetime
import urllib.request
import urllib.error

SUNKWI = "https://twitch-drops-api.sunkwi.com/v2/drops"
FENRIS = "https://twitch-drops.fenrisapps.com/campaigns"
TWITCHDROPS = "https://twitchdrops.app/"
STREAMDB = "https://www.streamdatabase.com/events"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) drops-radar/2.0"}

PLATFORM_HINTS = ("badge", "emote", "emoticon", "subscri", "sub token",
                  "bits", "turbo", "banner", "chat ", "profile", "avatar frame")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def now_iso():
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, as_json=True):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if as_json else body


def classify(rewards):
    names = [r["name"].lower() for r in rewards if r.get("name")]
    if names and all(any(h in n for h in PLATFORM_HINTS) for n in names):
        return "platform"
    return "game"


def fuzzy_key(c):
    """Chave para deduplicar entre fontes (que nem sempre tem o mesmo id)."""
    g = re.sub(r"[^a-z0-9]", "", (c.get("game") or "").lower())
    d = (c.get("start_at") or "")[:10]
    return (g, d)


# ---------------- fonte 1: sunkwi (ativos) ----------------

def sunkwi_rewards(rw):
    out, seen = [], set()
    for tbd in rw.get("timeBasedDrops") or []:
        mins = tbd.get("requiredMinutesWatched")
        for edge in tbd.get("benefitEdges") or []:
            b = (edge or {}).get("benefit") or {}
            key = b.get("id") or b.get("name")
            if b.get("name") and key not in seen:
                seen.add(key)
                out.append({"name": b["name"], "image": b.get("imageAssetURL"), "minutes": mins})
    return out


def carrega_sunkwi():
    d = fetch(SUNKWI)
    abertas, fechadas_ids = [], set()
    for camp in d.get("data") or []:
        for rw in camp.get("rewards") or []:
            if (rw.get("allow") or {}).get("channels"):
                fechadas_ids.add(rw.get("id"))
                continue
            if rw.get("status") not in ("ACTIVE", "UPCOMING"):
                continue
            game = rw.get("game") or {}
            rewards = sunkwi_rewards(rw)
            mins = [t.get("requiredMinutesWatched") for t in (rw.get("timeBasedDrops") or [])
                    if t.get("requiredMinutesWatched")]
            abertas.append({
                "id": rw.get("id"), "name": rw.get("name"), "status": rw.get("status"),
                "start_at": rw.get("startAt"), "end_at": rw.get("endAt"),
                "image": rw.get("imageURL"), "details_url": rw.get("detailsURL"),
                "game": game.get("displayName") or camp.get("gameDisplayName"),
                "game_slug": game.get("slug"), "game_box": camp.get("gameBoxArtURL"),
                "availability": "open", "required_minutes": max(mins) if mins else None,
                "reward_type": classify(rewards), "rewards": rewards, "src": "sunkwi",
            })
    return abertas, fechadas_ids, d.get("lastUpdatedAt")


# ---------------- fonte 2: fenris (em breve) ----------------

def _rsc_campaigns(html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    text = json.loads('"' + "".join(chunks) + '"')
    m = re.search(r'"campaigns":\[', text)
    if not m:
        raise ValueError("layout do fenris mudou")
    objs, i = [], text.index("{", m.end() - 1)
    while True:
        obj = _extract_obj(text, i)
        if not obj:
            break
        objs.append(json.loads(obj))
        j = i + len(obj)
        while j < len(text) and text[j] in " \n\t":
            j += 1
        if j < len(text) and text[j] == ",":
            i = text.index("{", j)
        else:
            break
    return objs


def _extract_obj(s, i):
    depth = 0
    start = i
    in_str = False
    esc = False
    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
        i += 1
    return None


def carrega_fenris():
    return _rsc_campaigns(fetch(FENRIS, as_json=False))


def _dt(s):
    return (s or "").replace("$D", "")


def normaliza_fenris(o):
    game = o.get("game") or {}
    rewards, seen, mins = [], set(), []
    for tbd in o.get("timeBasedDrops") or []:
        m = tbd.get("requiredMinutesWatched")
        if m:
            mins.append(m)
        for b in tbd.get("benefits") or []:
            key = b.get("benefitId") or b.get("name")
            if b.get("name") and key not in seen:
                seen.add(key)
                rewards.append({"name": b["name"], "image": b.get("imageAssetUrl"), "minutes": m})
    return {
        "id": o.get("id"), "name": o.get("name"), "status": None,
        "start_at": _dt(o.get("startAt")), "end_at": _dt(o.get("endAt")),
        "image": None, "details_url": FENRIS,
        "game": game.get("displayName"), "game_slug": game.get("slug"),
        "game_box": game.get("boxArtUrl"), "availability": "open",
        "required_minutes": max(mins) if mins else None,
        "reward_type": classify(rewards), "rewards": rewards, "src": "fenris",
    }


# ---------------- fonte 3: twitchdrops.app (lacunas) ----------------

def _attr(s, name):
    m = re.search(r'%s="([^"]*)"' % re.escape(name), s)
    return m.group(1) if m else None


def carrega_twitchdrops(agora):
    html = fetch(TWITCHDROPS, as_json=False)
    out = []
    for m in re.finditer(r'<a\b([^>]*\bgame-card\b[^>]*)>', html):
        attrs = m.group(1)
        if _attr(attrs, "data-allchannels") != "true":   # so aberto
            continue
        end = html.find("</a>", m.end())
        body = html[m.end():end] if end != -1 else ""
        start = _attr(attrs, "data-start")
        endat = _attr(attrs, "data-end")
        if endat and endat < agora:                       # ja expirou
            continue
        title_m = re.search(r'card-title">([^<]+)<', body)
        game = (title_m.group(1).strip() if title_m else (_attr(attrs, "data-game") or "").title())
        thumb = re.search(r'class="card-thumb"[^>]*src="([^"]+)"', body) \
            or re.search(r'src="([^"]+)"[^>]*class="card-thumb"', body)
        drops = _attr(attrs, "data-drops") or "?"
        rimgs = re.findall(r'class="reward-thumb"[^>]*src="([^"]+)"', body)
        rnames = [re.sub(r"\s+", " ", x).strip()
                  for x in re.findall(r'class="reward-name">([^<]*)<', body)]
        rewards = []
        for k in range(max(len(rimgs), len(rnames))):
            nm = rnames[k] if k < len(rnames) else "Recompensa"
            im = rimgs[k] if k < len(rimgs) else None
            if nm:
                rewards.append({"name": nm, "image": im, "minutes": None})
        out.append({
            "id": None,
            "name": ("%s drop%s" % (drops, "" if drops == "1" else "s")),
            "status": "UPCOMING" if (start or "") > agora else "ACTIVE",
            "start_at": start, "end_at": endat,
            "image": thumb.group(1) if thumb else None,
            "details_url": "https://twitchdrops.app/game/" + (_attr(attrs, "data-slug") or ""),
            "game": game, "game_slug": _attr(attrs, "data-slug"), "game_box": None,
            "availability": "open",
            "required_minutes": None,
            "reward_type": classify(rewards), "rewards": rewards, "src": "twitchdrops",
        })
    return out


# ---------------- fonte 4: streamdatabase (badges chegando) ----------------

def carrega_badges(agora):
    html = fetch(STREAMDB, as_json=False)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("layout do streamdatabase mudou")
    evs = (((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}).get("initialEvents")) or []
    out = []
    for e in evs:
        if e.get("hidden"):
            continue
        sd = e.get("start_at_date")
        if not sd:
            continue
        st = (e.get("start_at_time") or "00:00")[:5]
        start_iso = "%sT%s:00Z" % (sd, st)
        if start_iso <= agora:                              # so os que ainda vao comecar
            continue
        ed = e.get("end_at_date")
        end_iso = ("%sT%s:00Z" % (ed, (e.get("end_at_time") or "23:59")[:5])) if ed else None
        images = []
        for b in e.get("twitch_global_badges") or []:
            url = (((b.get("current") or {}).get("version") or {}).get("image_url_4x"))
            if url and url not in images:
                images.append(url)
        out.append({
            "title": e.get("title"),
            "start_at": start_iso, "end_at": end_iso,
            "note": (e.get("content") or "").strip()[:180] or None,
            "images": images[:8],
        })
    out.sort(key=lambda b: b["start_at"])
    return out


# ---------------- principal ----------------

def write(result):
    os.makedirs("data", exist_ok=True)
    with open("data/drops.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("ok=%s counts=%s warn=%s error=%s" % (
        result["ok"], result.get("counts"), result.get("warn"), result.get("error")))


def coletar(incluir_badges=True):
    """Junta as fontes e devolve {camps, badges, fechadas, erros, source_updated}.
    Usado pelo main() (site) e pelo alerta_drops.py (vigia local)."""
    agora = now_utc().strftime("%Y-%m-%dT%H:%M:%S.999Z")
    camps, fechadas_ids, erros = [], set(), []
    badges, src_upd = [], None

    # 1) sunkwi (ativos, com aberto/fechado)
    try:
        camps, fechadas_ids, src_upd = carrega_sunkwi()
    except Exception as e:
        erros.append("sunkwi: %s" % type(e).__name__)

    ids_ja = {c["id"] for c in camps if c.get("id")}
    keys_ja = {fuzzy_key(c) for c in camps}

    # 2) fenris (em breve + lacunas de ativo)
    try:
        for o in carrega_fenris():
            c = normaliza_fenris(o)
            if not c["id"] or c["id"] in ids_ja or c["id"] in fechadas_ids:
                continue
            if c["end_at"] and c["end_at"] < agora:
                continue
            c["status"] = "UPCOMING" if (c["start_at"] or "") > agora else "ACTIVE"
            camps.append(c)
            ids_ja.add(c["id"])
            keys_ja.add(fuzzy_key(c))
    except Exception as e:
        erros.append("fenris: %s" % type(e).__name__)

    # 3) twitchdrops.app (preenche o que 1 e 2 perdem)
    try:
        for c in carrega_twitchdrops(agora):
            k = fuzzy_key(c)
            if k in keys_ja:
                continue
            camps.append(c)
            keys_ja.add(k)
    except Exception as e:
        erros.append("twitchdrops: %s" % type(e).__name__)

    # 4) badges chegando
    if incluir_badges:
        try:
            badges = carrega_badges(agora)
        except Exception as e:
            erros.append("streamdatabase(badges): %s" % type(e).__name__)

    order_status = {"UPCOMING": 0, "ACTIVE": 1}
    camps.sort(key=lambda c: (
        order_status.get(c["status"], 2),
        0 if c["reward_type"] == "game" else 1,
        c.get("start_at") or "",
    ))
    return {"camps": camps, "badges": badges, "fechadas": fechadas_ids,
            "erros": erros, "source_updated": src_upd}


def main():
    result = {
        "updated_at": now_iso(), "ok": False, "source": "sunkwi+fenris+twitchdrops+streamdatabase",
        "source_updated": None, "counts": {}, "campaigns": [], "badges": [],
        "error": None, "warn": None, "raw_hint": None,
    }
    col = coletar()
    camps, fechadas_ids, erros = col["camps"], col["fechadas"], col["erros"]
    result["source_updated"] = col["source_updated"]
    result["badges"] = col["badges"]

    if camps:
        result["ok"] = True
        if erros:
            result["warn"] = "Fonte parcial fora do ar: " + "; ".join(erros)
    else:
        result["error"] = "Nenhuma fonte de drops respondeu (%s)." % ("; ".join(erros) or "?")

    result["campaigns"] = camps
    result["counts"] = {
        "total": len(camps),
        "upcoming": sum(1 for c in camps if c["status"] == "UPCOMING"),
        "active": sum(1 for c in camps if c["status"] == "ACTIVE"),
        "game_drops": sum(1 for c in camps if c["reward_type"] == "game"),
        "platform": sum(1 for c in camps if c["reward_type"] == "platform"),
        "badges": len(result["badges"]),
        "fechadas_descartadas": len(fechadas_ids),
    }
    write(result)


if __name__ == "__main__":
    main()
