#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitch Drops Radar - checador.

Fonte: API publica agregadora de drops (sunkwi), que ja resolve o scraping da Twitch.
  -> sem token, sem F12, sem conta descartavel, sem anti-bot, sem risco de ban.
Este script NAO toca a Twitch: so consome JSON de terceiro. Pode rodar em qualquer lugar.

Regras (pedido do dono):
  - Campanha FECHADA (allow.channels com lista = so canais especificos) e DESCARTADA.
    Fica so o que e aberto a qualquer streamer.
  - EXPIRED e descartado. Fica ACTIVE + UPCOMING (com UPCOMING no topo).
  - reward_type: "game"     -> item de jogo (drop "de verdade")
                 "platform" -> badge/emote/coisa da Twitch (ruido, filtravel no site)
"""
import json
import os
import datetime
import urllib.request
import urllib.error

SOURCE = "https://twitch-drops-api.sunkwi.com/v2/drops"

PLATFORM_HINTS = ("badge", "emote", "emoticon", "subscri", "sub token",
                  "bits", "turbo", "banner", "chat ", "profile", "avatar frame")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "drops-radar/1.0 (github actions)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def rewards_list(rw):
    """Recompensas de verdade (com imagem) vindas dos timeBasedDrops -> benefitEdges -> benefit."""
    out, seen = [], set()
    for tbd in rw.get("timeBasedDrops") or []:
        for edge in tbd.get("benefitEdges") or []:
            b = (edge or {}).get("benefit") or {}
            key = b.get("id") or b.get("name")
            if b.get("name") and key not in seen:
                seen.add(key)
                out.append({"name": b["name"], "image": b.get("imageAssetURL")})
    return out


def classify(rewards):
    names = [r["name"].lower() for r in rewards if r.get("name")]
    if names and all(any(h in n for h in PLATFORM_HINTS) for n in names):
        return "platform"
    return "game"


def required_minutes(rw):
    mins = [t.get("requiredMinutesWatched") for t in (rw.get("timeBasedDrops") or []) if t.get("requiredMinutesWatched")]
    return max(mins) if mins else None


def normalize(camp, rw):
    allow = rw.get("allow") or {}
    channels = [c.get("displayName") for c in (allow.get("channels") or []) if c and c.get("displayName")]
    game = rw.get("game") or {}
    rewards = rewards_list(rw)
    return {
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
        "availability": "restricted" if channels else "open",
        "required_minutes": required_minutes(rw),
        "reward_type": classify(rewards),
        "rewards": rewards,
    }


def write(result):
    os.makedirs("data", exist_ok=True)
    with open("data/drops.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("ok=%s counts=%s error=%s" % (result["ok"], result.get("counts"), result.get("error")))


def main():
    result = {
        "updated_at": now_iso(),
        "ok": False,
        "source": "sunkwi",
        "source_updated": None,
        "counts": {},
        "campaigns": [],
        "error": None,
        "raw_hint": None,
    }
    try:
        d = fetch(SOURCE)
        result["source_updated"] = d.get("lastUpdatedAt")

        todas = []
        for camp in d.get("data") or []:
            for rw in camp.get("rewards") or []:
                todas.append(normalize(camp, rw))

        # so vivas (ACTIVE/UPCOMING); expiradas fora
        vivas = [c for c in todas if c["status"] in ("ACTIVE", "UPCOMING")]
        # so abertas a qualquer streamer; fechadas fora
        camps = [c for c in vivas if c["availability"] == "open"]

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
            "fechadas_descartadas": sum(1 for c in vivas if c["availability"] != "open"),
            "expiradas_descartadas": len(todas) - len(vivas),
        }
        result["ok"] = True

    except urllib.error.HTTPError as e:
        result["error"] = "A fonte de drops respondeu HTTP %s." % e.code
        try:
            result["raw_hint"] = e.read().decode("utf-8")[:500]
        except Exception:
            pass
    except Exception as e:
        result["error"] = "Nao consegui ler a fonte de drops (%s)." % type(e).__name__
        result["raw_hint"] = str(e)[:500]

    write(result)


if __name__ == "__main__":
    main()
