#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitch Drops Radar - checador.

Roda no GitHub Actions (NUNCA na maquina do dono, pra nao vazar IP real pra Twitch).
Busca as campanhas de drops via GQL, categoriza e escreve data/drops.json.

Regras:
  - Campanha FECHADA (allow.channels com lista = so canais especificos) e DESCARTADA aqui:
    o dono do site so quer as abertas a qualquer streamer (allow.channels vazio).
  - reward_type: "game"     -> item de jogo (drop "de verdade")
                 "platform" -> badge/emote/coisa da Twitch (ruido, filtravel no site)

So usa a biblioteca padrao (urllib) -> sem 'pip install', sem dependencia.
"""
import json
import os
import datetime
import urllib.request
import urllib.error

GQL_URL = "https://gql.twitch.tv/gql"
# client-id publico do site da Twitch (o mesmo que o navegador usa em toda pagina)
WEB_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

# Query "crua" (nao usa hash persistido, entao nao quebra quando a Twitch troca os hashes).
QUERY = """
query ViewerDropsDashboard {
  currentUser {
    id
    login
    dropCampaigns {
      id
      name
      status
      startAt
      endAt
      detailsURL
      imageURL
      game { id slug displayName boxArtURL }
      allow { channels { id displayName } }
      timeBasedDrops {
        id
        name
        benefitEdges {
          benefit { id name imageAssetURL game { id displayName } }
        }
      }
    }
  }
}
"""

# Se TODAS as recompensas de uma campanha baterem nessas pistas, ela e "plataforma" (badge/emote/etc).
PLATFORM_HINTS = ("badge", "emote", "emoticon", "subscri", "sub token",
                  "bits", "turbo", "banner", "chat ", "profile", "avatar frame")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gql(query, token):
    headers = {"Client-ID": WEB_CLIENT_ID, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "OAuth " + token
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(GQL_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def classify_reward(camp):
    names = []
    for tbd in camp.get("timeBasedDrops") or []:
        for edge in tbd.get("benefitEdges") or []:
            b = (edge or {}).get("benefit") or {}
            if b.get("name"):
                names.append(b["name"].lower())
    if names and all(any(h in n for h in PLATFORM_HINTS) for n in names):
        return "platform"
    return "game"


def rewards_list(camp):
    out, seen = [], set()
    for tbd in camp.get("timeBasedDrops") or []:
        for edge in tbd.get("benefitEdges") or []:
            b = (edge or {}).get("benefit") or {}
            key = b.get("id") or b.get("name")
            if b.get("name") and key not in seen:
                seen.add(key)
                out.append({"name": b["name"], "image": b.get("imageAssetURL")})
    return out


def normalize(camp):
    allow = camp.get("allow") or {}
    channels = [c.get("displayName") for c in (allow.get("channels") or []) if c and c.get("displayName")]
    game = camp.get("game") or {}
    return {
        "id": camp.get("id"),
        "name": camp.get("name"),
        "status": camp.get("status"),
        "start_at": camp.get("startAt"),
        "end_at": camp.get("endAt"),
        "image": camp.get("imageURL"),
        "details_url": camp.get("detailsURL"),
        "game": game.get("displayName"),
        "game_slug": game.get("slug"),
        "game_box": game.get("boxArtURL"),
        "availability": "restricted" if channels else "open",
        "channels": channels,
        "reward_type": classify_reward(camp),
        "rewards": rewards_list(camp),
    }


def write(result):
    os.makedirs("data", exist_ok=True)
    with open("data/drops.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("ok=%s modo=%s counts=%s erro=%s" % (
        result["ok"], result["auth_mode"], result.get("counts"), result.get("error")))


def main():
    token = os.environ.get("TWITCH_OAUTH", "").strip()
    result = {
        "updated_at": now_iso(),
        "ok": False,
        "auth_mode": "token" if token else "anonymous",
        "counts": {},
        "campaigns": [],
        "error": None,
        "raw_hint": None,
    }
    try:
        data = gql(QUERY, token)

        if data.get("errors"):
            result["error"] = "A Twitch devolveu erro de GQL (veja raw_hint)."
            result["raw_hint"] = json.dumps(data["errors"], ensure_ascii=False)[:900]

        user = (data.get("data") or {}).get("currentUser")
        if not user:
            result["error"] = result["error"] or (
                "currentUser veio vazio. A lista de drops e por usuario: "
                "defina o secret TWITCH_OAUTH com o token de uma conta descartavel."
            )
            write(result)
            return

        todas = [normalize(c) for c in (user.get("dropCampaigns") or []) if c]

        # Fechadas (so canais especificos) ficam DE FORA do site.
        camps = [c for c in todas if c["availability"] == "open"]

        # Ordena: EM BREVE antes de ATIVO; item de jogo antes de badge; data.
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
            "fechadas_descartadas": len(todas) - len(camps),
        }
        result["ok"] = True

    except urllib.error.HTTPError as e:
        result["error"] = "HTTP %s ao chamar a GQL." % e.code
        try:
            result["raw_hint"] = e.read().decode("utf-8")[:900]
        except Exception:
            pass
    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)

    write(result)


if __name__ == "__main__":
    main()
