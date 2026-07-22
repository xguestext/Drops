#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitch Drops Radar - checador (2 fontes).

Este script NAO toca a Twitch: so consome fontes de terceiros. Pode rodar em qualquer lugar.

  1) sunkwi  (API JSON estavel)  -> campanhas ATIVAS, com allow.channels (aberto/fechado)
  2) fenris  (HTML SSR raspado)  -> unica fonte com campanhas FUTURAS ("em breve"),
     que e o que o dono do site mais quer. Nao traz aberto/fechado, MAS verificado
     empiricamente (2026-07-22): fenris nao lista nenhuma campanha fechada da sunkwi.
     Trava extra: qualquer id que a sunkwi conheca como fechado e barrado.

Regras (pedido do dono):
  - So campanhas ABERTAS a qualquer streamer. Fechadas (canais especificos) descartadas.
  - EXPIRED descartado. UPCOMING no topo.
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
UA = {"User-Agent": "drops-radar/1.0 (github actions; site pessoal de drops)"}

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


# ---------------- fonte 1: sunkwi (ativos) ----------------

def sunkwi_rewards(rw):
    out, seen = [], set()
    for tbd in rw.get("timeBasedDrops") or []:
        for edge in tbd.get("benefitEdges") or []:
            b = (edge or {}).get("benefit") or {}
            key = b.get("id") or b.get("name")
            if b.get("name") and key not in seen:
                seen.add(key)
                out.append({"name": b["name"], "image": b.get("imageAssetURL")})
    return out


def carrega_sunkwi():
    """-> (abertas_vivas, ids_fechadas, source_updated)"""
    d = fetch(SUNKWI)
    abertas, fechadas_ids = [], set()
    for camp in d.get("data") or []:
        for rw in camp.get("rewards") or []:
            allow = rw.get("allow") or {}
            channels = allow.get("channels") or []
            if channels:
                fechadas_ids.add(rw.get("id"))
                continue
            if rw.get("status") not in ("ACTIVE", "UPCOMING"):
                continue
            game = rw.get("game") or {}
            rewards = sunkwi_rewards(rw)
            mins = [t.get("requiredMinutesWatched") for t in (rw.get("timeBasedDrops") or [])
                    if t.get("requiredMinutesWatched")]
            abertas.append({
                "id": rw.get("id"),
                "name": rw.get("name"),
                "status": rw.get("status"),
                "start_at": rw.get("startAt"),
                "end_at": rw.get("endAt"),
                "image": rw.get("imageURL"),
                "details_url": rw.get("detailsURL"),
                "game": game.get("displayName") or camp.get("gameDisplayName"),
                "game_slug": game.get("slug"),
                "game_box": camp.get("gameBoxArtURL"),
                "availability": "open",
                "required_minutes": max(mins) if mins else None,
                "reward_type": classify(rewards),
                "rewards": rewards,
            })
    return abertas, fechadas_ids, d.get("lastUpdatedAt")


# ---------------- fonte 2: fenris (em breve) ----------------

def _extract_obj(s, i):
    """Extrai um objeto JSON balanceado comecando em s[i] == '{'."""
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
    """Raspa o payload SSR (Next.js RSC) da pagina de campanhas -> lista de campanhas cruas."""
    html = fetch(FENRIS, as_json=False)
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    text = json.loads('"' + "".join(chunks) + '"')
    m = re.search(r'"campaigns":\[', text)
    if not m:
        raise ValueError("layout do fenris mudou: nao achei \"campaigns\":[")
    objs = []
    i = text.index("{", m.end() - 1)
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


def _dt(s):
    # datas do RSC vem como "$D2026-07-23T02:00:00.000Z"
    return (s or "").replace("$D", "")


def normaliza_fenris(o):
    game = o.get("game") or {}
    rewards, seen = [], set()
    mins = []
    for tbd in o.get("timeBasedDrops") or []:
        if tbd.get("requiredMinutesWatched"):
            mins.append(tbd["requiredMinutesWatched"])
        for b in tbd.get("benefits") or []:
            key = b.get("benefitId") or b.get("name")
            if b.get("name") and key not in seen:
                seen.add(key)
                rewards.append({"name": b["name"], "image": b.get("imageAssetUrl")})
    return {
        "id": o.get("id"),
        "name": o.get("name"),
        "status": None,  # decidido pelo relogio
        "start_at": _dt(o.get("startAt")),
        "end_at": _dt(o.get("endAt")),
        "image": None,
        "details_url": FENRIS,
        "game": game.get("displayName"),
        "game_slug": game.get("slug"),
        "game_box": game.get("boxArtUrl"),
        "availability": "open",  # fenris nao lista fechadas (verificado); trava extra abaixo
        "required_minutes": max(mins) if mins else None,
        "reward_type": classify(rewards),
        "rewards": rewards,
    }


# ---------------- principal ----------------

def write(result):
    os.makedirs("data", exist_ok=True)
    with open("data/drops.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("ok=%s counts=%s error=%s warn=%s" % (
        result["ok"], result.get("counts"), result.get("error"), result.get("warn")))


def main():
    result = {
        "updated_at": now_iso(),
        "ok": False,
        "source": "sunkwi+fenris",
        "source_updated": None,
        "counts": {},
        "campaigns": [],
        "error": None,
        "warn": None,
        "raw_hint": None,
    }
    agora = now_utc().strftime("%Y-%m-%dT%H:%M:%S.999Z")

    camps, fechadas_ids = [], set()
    erros = []

    # fonte 1: ativos
    try:
        camps, fechadas_ids, src_upd = carrega_sunkwi()
        result["source_updated"] = src_upd
    except Exception as e:
        erros.append("sunkwi: %s" % type(e).__name__)

    # fonte 2: em breve (+ eventuais ativos que a sunkwi nao pegou)
    try:
        ids_ja = {c["id"] for c in camps}
        for o in carrega_fenris():
            c = normaliza_fenris(o)
            if not c["id"] or c["id"] in ids_ja:
                continue
            if c["id"] in fechadas_ids:          # trava: fechado na sunkwi nao entra
                continue
            if c["end_at"] and c["end_at"] < agora:   # ja expirou
                continue
            c["status"] = "UPCOMING" if (c["start_at"] or "") > agora else "ACTIVE"
            camps.append(c)
            ids_ja.add(c["id"])
    except Exception as e:
        erros.append("fenris(em-breve): %s" % type(e).__name__)

    if camps:
        result["ok"] = True
        if erros:
            result["warn"] = "Fonte parcial fora do ar: " + "; ".join(erros)
    else:
        result["error"] = "Nenhuma fonte de drops respondeu (%s)." % ("; ".join(erros) or "?")

    # UPCOMING no topo; item de jogo antes de badge; por data de inicio
    order_status = {"UPCOMING": 0, "ACTIVE": 1}
    camps.sort(key=lambda c: (
        order_status.get(c["status"], 2),
        0 if c["reward_type"] == "game" else 1,
        c.get("start_at") or "",
    ))

    result["campaigns"] = camps
    result["counts"] = {
        "total": len(camps),
        "upcoming": sum(1 for c in camps if c["status"] == "UPCOMING"),
        "active": sum(1 for c in camps if c["status"] == "ACTIVE"),
        "game_drops": sum(1 for c in camps if c["reward_type"] == "game"),
        "platform": sum(1 for c in camps if c["reward_type"] == "platform"),
        "fechadas_descartadas": len(fechadas_ids),
    }

    write(result)


if __name__ == "__main__":
    main()
