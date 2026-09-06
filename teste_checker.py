#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do radar. Rode com: python teste_checker.py

Os de baixo NAO tocam a rede: sao respostas REAIS da Twitch capturadas em
06/09/2026 — o incidente do Minecraft (badge de canal), o ALGS do Apex (161
canais convidados, que o dono pegou no feed como se fosse aberto), badges
disfarcadas de item (Onimusha Armament) e drop de sub. Servem pra garantir que
a peneira continua separando isso mesmo depois de alguem mexer no codigo.

`python teste_checker.py --ao-vivo` acrescenta os que falam com a Twitch.
"""
import copy
import datetime
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checker
import twitch_gql as tw

FALHAS = []


def checa(nome, condicao, detalhe=""):
    if condicao:
        print("  ok   %s" % nome)
    else:
        print("  FALHOU %s %s" % (nome, detalhe))
        FALHAS.append(nome)


# ── material real, copiado das respostas da Twitch em 06/09/2026 ─────────────

def _drop(minutos, subs, nome, tipo, img):
    return {"requiredMinutesWatched": minutos, "requiredSubs": subs,
            "benefitEdges": [{"benefit": {"name": nome, "imageAssetURL": img,
                                          "distributionType": tipo}}]}


REWARD = "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/%s.png"
BADGE_IMG = "https://static-cdn.jtvnw.net/badges/v1/%s/3"
ABERTA = {"isEnabled": False, "channels": []}

# O que os canais de Minecraft respondiam na hora em que o piloto abriu a live:
# badge do proprio streamer, um canal so, e ainda por sub.
MINECRAFT_BADGE = {
    "id": "e229e5fc-69b3-474a-9845-ba97b1539a97", "name": "LACY X MARLON MARATHON",
    "game": None, "detailsURL": "", "startAt": "2026-09-01T19:00:00Z",
    "endAt": "2026-09-12T19:00:00Z", "imageURL": BADGE_IMG % "983f4bdc",
    "allow": {"isEnabled": True, "channels": [{"id": "494543675", "name": "lacy"}]},
    "timeBasedDrops": [_drop(0, 1, "LACY X MARLON MARATHON", "BADGE", BADGE_IMG % "983f4bdc")],
}

# O que o dono pegou no feed como "aberto": item de jogo de verdade, mas so pra
# 161 canais convidados ("including playapex, NiceWigg, algs1_team1... and more").
APEX_FECHADA = {
    "id": "apex-algs", "name": "ALGS Split 2 PL MD 9", "detailsURL": "https://algs.ea.com/",
    "game": {"id": "511224", "name": "Apex Legends"},
    "startAt": "2026-09-04T00:00:00Z", "endAt": "2026-09-07T00:00:00Z", "imageURL": REWARD % "a",
    "allow": {"isEnabled": True, "channels": [{"name": n} for n in
              ("playapex", "nicewigg", "algs1_team1", "algs1_team2", "algs1_team3")]},
    "timeBasedDrops": [_drop(15, 0, "APEX Pack", "DIRECT_ENTITLEMENT", REWARD % "c49"),
                       _drop(60, 0, "Sushi Nessie Gun Charm", "DIRECT_ENTITLEMENT", REWARD % "989")],
}

# Drop aberto de verdade (a live da Misaune das 07:18 confirmou esse).
CIV_ABERTA = {
    "id": "a82abb82-628f-4df5-a2bb-5df8cc373983", "name": "Civ VII PAX 26 Livestream",
    "status": "ACTIVE", "startAt": "2026-09-05T16:30:00Z", "endAt": "2036-10-03T16:29:59.999Z",
    "imageURL": REWARD % "41d417d4", "detailsURL": "https://civilization.2k.com/twitch-drops/",
    "description": "Watch for 15 minutes and claim the reward: Exploration Age Banner!",
    "owner": {"id": "e918", "name": "2K Games"},
    "game": {"id": "2064093867", "name": "Sid Meier's Civilization VII"},
    "allow": ABERTA,
    "timeBasedDrops": [_drop(15, 0, "Exploration Age Banner", "DIRECT_ENTITLEMENT", REWARD % "dd2e00f2")],
}

# Badge da Twitch ABERTA a todos, com a imagem servida da pasta dos ITENS:
# e o que enganava a regra antiga (imagem REWARD => "game").
ONIMUSHA_BADGE_ABERTA = {
    "id": "onimusha-badge", "name": "Onimusha Armament", "detailsURL": "",
    "game": {"id": "1", "name": "Onimusha: Way of the Sword"},
    "startAt": "2026-09-01T00:00:00Z", "endAt": "2036-09-30T00:00:00Z", "imageURL": REWARD % "b",
    "allow": ABERTA,
    "timeBasedDrops": [_drop(60, 0, "Onimusha Armament", "BADGE", REWARD % "onimusha")],
}

# Drop de item que so se ganha sendo sub.
DELTA_SUB = {
    "id": "delta-sub", "name": "ANNIVERSARY PREVIEW SUB", "detailsURL": "",
    "game": {"id": "2", "name": "Delta Force"},
    "startAt": "2026-09-01T00:00:00Z", "endAt": "2036-09-30T00:00:00Z", "imageURL": REWARD % "d",
    "allow": ABERTA,
    "timeBasedDrops": [_drop(0, 1, "Anniversary Skin", "DIRECT_ENTITLEMENT", REWARD % "delta")],
}

# Colecionavel da Twitch (Great Ball): nem item de jogo, nem badge — e pede sub.
GREAT_BALL = {
    "id": "great-ball", "name": "First Partners Collection", "detailsURL": "",
    "game": {"id": "509663", "name": "Special Events"},
    "startAt": "2026-09-01T00:00:00Z", "endAt": "2036-09-30T00:00:00Z", "imageURL": REWARD % "g",
    "allow": ABERTA,
    "timeBasedDrops": [_drop(20, 2, "Great Ball", "UNSPECIFIED", REWARD % "greatball")],
}

# Jogo pequeno: drop aberto que so UM canal no mundo estava transmitindo.
KIRKA_ABERTA = {
    "id": "kirka-spore", "name": "Spore", "detailsURL": "",
    "game": {"id": "3", "name": "Kirka.io"},
    "startAt": "2026-09-01T00:00:00Z", "endAt": "2036-09-30T00:00:00Z", "imageURL": REWARD % "k",
    "allow": ABERTA,
    "timeBasedDrops": [_drop(900, 0, "Spore", "DIRECT_ENTITLEMENT", REWARD % "ec6")],
}

# Resposta no formato ANTIGO (persisted query): sem allow, sem distributionType.
SEM_ALLOW = {
    "id": "velho", "name": "Global Launch Welcome Kit", "game": None,
    "startAt": "2026-08-12T00:00:00Z", "endAt": "2036-09-08T05:59:59.999Z", "imageURL": "",
    "timeBasedDrops": [{"requiredMinutesWatched": 120, "benefitEdges": [{"benefit": {
        "name": "Global Launch Drops Kit", "imageAssetURL": REWARD % "5ddbd64a"}}]}],
}

# Campanha com dois degraus (o segundo e o que vale): 0 min e 360 min.
DOIS_DEGRAUS = {
    "id": "dois-degraus", "name": "Duas etapas", "detailsURL": "", "imageURL": "",
    "startAt": None, "endAt": None, "allow": ABERTA,
    "timeBasedDrops": [_drop(0, 0, "Entrada", "DIRECT_ENTITLEMENT", REWARD % "a"),
                       _drop(360, 0, "Premio", "DIRECT_ENTITLEMENT", REWARD % "b")],
}


def teste_tipo_da_campanha():
    print("tipo_da_campanha (pelo distributionType; imagem so como plano B)")
    checa("item de jogo e game", tw.tipo_da_campanha(APEX_FECHADA) == "game")
    checa("badge de canal e badge", tw.tipo_da_campanha(MINECRAFT_BADGE) == "badge")
    checa("badge com imagem de ITEM continua badge (Onimusha Armament)",
          tw.tipo_da_campanha(ONIMUSHA_BADGE_ABERTA) == "badge", tw.tipo_da_campanha(ONIMUSHA_BADGE_ABERTA))
    checa("colecionavel UNSPECIFIED e platform", tw.tipo_da_campanha(GREAT_BALL) == "platform")
    checa("sem distributionType cai na pasta da imagem", tw.tipo_da_campanha(SEM_ALLOW) == "game")
    misto = copy.deepcopy(CIV_ABERTA)
    misto["timeBasedDrops"].append(_drop(30, 0, "Badge extra", "BADGE", BADGE_IMG % "x"))
    checa("item + badge continua game", tw.tipo_da_campanha(misto) == "game")
    checa("campanha sem premio nenhum nao vira game",
          tw.tipo_da_campanha({"timeBasedDrops": [], "imageURL": ""}) != "game")


def teste_aberta_e_permitidos():
    print("aberta_a_todos / canais_permitidos (o `allow` da campanha)")
    checa("Civ VII e aberta", tw.aberta_a_todos(CIV_ABERTA) is True)
    checa("Apex ALGS e FECHADA", tw.aberta_a_todos(APEX_FECHADA) is False)
    checa("badge de canal e fechada", tw.aberta_a_todos(MINECRAFT_BADGE) is False)
    checa("sem allow devolve None (nao se sabe)", tw.aberta_a_todos(SEM_ALLOW) is None)
    checa("lista de convidados do Apex", tw.canais_permitidos(APEX_FECHADA)[:2] == ["playapex", "nicewigg"])
    checa("aberta nao tem lista", tw.canais_permitidos(CIV_ABERTA) == [])


def teste_sub_e_minutos():
    print("exige_sub / minutos_de")
    checa("drop de sub exige sub", tw.exige_sub(DELTA_SUB) is True)
    checa("Great Ball exige sub", tw.exige_sub(GREAT_BALL) is True)
    checa("Civ nao exige sub", tw.exige_sub(CIV_ABERTA) is False)
    checa("sem info de sub nao exige", tw.exige_sub(SEM_ALLOW) is False)
    checa("minutos do Civ = 15", tw.minutos_de(CIV_ABERTA) == 15)
    checa("subs_necessarios: Delta pede 1", tw.subs_necessarios(DELTA_SUB) == 1)
    checa("subs_necessarios: Civ pede 0", tw.subs_necessarios(CIV_ABERTA) == 0)
    checa("resgate do Civ", tw.resgate(CIV_ABERTA) == "assistir 15 min", tw.resgate(CIV_ABERTA))
    checa("resgate do Delta", tw.resgate(DELTA_SUB) == "dar 1 sub", tw.resgate(DELTA_SUB))
    checa("resgate do Great Ball", tw.resgate(GREAT_BALL) == "dar 2 subs", tw.resgate(GREAT_BALL))
    checa("resgate do Kirka (15h)", tw.resgate(KIRKA_ABERTA) == "assistir 15h", tw.resgate(KIRKA_ABERTA))
    misto = copy.deepcopy(CIV_ABERTA)
    misto["timeBasedDrops"].append(_drop(0, 1, "Skin de sub", "DIRECT_ENTITLEMENT", REWARD % "z"))
    checa("resgate com os dois caminhos", tw.resgate(misto) == "assistir 15 min ou dar 1 sub", tw.resgate(misto))
    checa("pega o menor watch de verdade (>0)", tw.minutos_de(DOIS_DEGRAUS) == 360, tw.minutos_de(DOIS_DEGRAUS))
    checa("drop so de sub nao tem minutos farmaveis", tw.minutos_de(DELTA_SUB) == 0)
    checa("nao explode com lista vazia", tw.minutos_de({}) == 0)


def _camp(fonte, categoria=None, canais=1, nome=None):
    c = checker._campanha_vazia(fonte, categoria or ((fonte.get("game") or {}).get("name") or "Jogo"),
                                "capa.jpg", "slug")
    if nome:
        c["id"] = nome
        c["name"] = nome
    c["canais_vistos"] = ["canal%d" % i for i in range(canais)]
    return c


def teste_formato_do_feed():
    """O bot e o site leem campos com nome fixo — nao podem sumir."""
    print("formato que o bot e o site esperam")
    c = _camp(CIV_ABERTA)
    for campo in ("id", "name", "status", "start_at", "end_at", "game", "game_box",
                  "availability", "channels", "canais_permitidos", "required_minutes",
                  "requer_sub", "subs_necessarios", "resgate", "reward_type", "tipo_premio",
                  "rewards", "image", "details_url", "src", "dono", "descricao"):
        checa("campo %s existe" % campo, campo in c)
    checa("start_at vem da campanha", c["start_at"] == "2026-09-05T16:30:00Z", c["start_at"])
    checa("availability open", c["availability"] == "open")
    checa("reward_type game", c["reward_type"] == "game")
    checa("dono e a 2K", c["dono"] == "2K Games")
    f = _camp(APEX_FECHADA)
    checa("Apex sai como closed", f["availability"] == "closed")
    checa("com os canais convidados", f["canais_permitidos"] == 5 and f["channels"][0] == "playapex")
    v = _camp(SEM_ALLOW, "GunZ: The Duel")
    checa("sem allow sai como unknown", v["availability"] == "unknown", v["availability"])
    checa("rewards trazem tipo e sub", "type" in c["rewards"][0] and "subs" in c["rewards"][0])


def teste_peneira():
    print("peneirar (o que vai pro site e por que)")
    campanhas = [
        _camp(CIV_ABERTA), _camp(KIRKA_ABERTA), _camp(APEX_FECHADA), _camp(MINECRAFT_BADGE, "Minecraft"),
        _camp(ONIMUSHA_BADGE_ABERTA), _camp(DELTA_SUB), _camp(GREAT_BALL),
        _camp(SEM_ALLOW, "GunZ: The Duel"), _camp(CIV_ABERTA, nome="Fortnite drops"),
    ]
    campanhas[-1]["game"] = "Fortnite"
    b = checker.peneirar(campanhas, ["fortnite"])
    nomes = lambda k: sorted(c["name"] for c in b[k])
    checa("abertas = Civ, Kirka (1 canal so tambem vale) e o drop de sub, marcado",
          nomes("abertas") == ["ANNIVERSARY PREVIEW SUB", "Civ VII PAX 26 Livestream", "Spore"], nomes("abertas"))
    delta = next(c for c in b["abertas"] if c["name"] == "ANNIVERSARY PREVIEW SUB")
    checa("drop de sub vem marcado", delta["requer_sub"] and delta["subs_necessarios"] == 1
          and delta["resgate"] == "dar 1 sub", (delta["requer_sub"], delta["subs_necessarios"], delta["resgate"]))
    checa("Apex ALGS vai pra FECHADAS", nomes("fechadas") == ["ALGS Split 2 PL MD 9"], nomes("fechadas"))
    checa("badge de canal vai pra de_canal", nomes("de_canal") == ["LACY X MARLON MARATHON"])
    checa("badge aberta e Great Ball vao pra badges_abertas",
          nomes("badges_abertas") == ["First Partners Collection", "Onimusha Armament"], nomes("badges_abertas"))
    checa("sem allow vai pra sem_info", nomes("sem_info") == ["Global Launch Welcome Kit"])
    checa("jogos-fora manda", nomes("fora_da_lista") == ["Fortnite drops"])


def teste_regressoes():
    """Os casos que ja vazaram pro feed NUNCA mais podem virar drop aberto."""
    print("regressoes (06/09/2026)")
    b = checker.peneirar([_camp(copy.deepcopy(MINECRAFT_BADGE), "Minecraft") for _ in range(6)], [])
    checa("Minecraft (badges de canal) nao produz drop", b["abertas"] == [] and b["badges_abertas"] == [])
    b = checker.peneirar([_camp(APEX_FECHADA)], [])
    checa("Apex ALGS (161 convidados) nao entra como aberto", b["abertas"] == [])
    zevent = copy.deepcopy(APEX_FECHADA); zevent["name"] = "ZEVENT 2026"; zevent["game"] = {"name": "ZEVENT"}
    zevent["allow"] = {"isEnabled": True, "channels": [{"name": "canal%d" % i} for i in range(338)]}
    b = checker.peneirar([_camp(zevent)], [])
    checa("ZEVENT (338 convidados) idem", b["abertas"] == [] and len(b["fechadas"]) == 1)
    b = checker.peneirar([_camp(ONIMUSHA_BADGE_ABERTA)], [])
    checa("badge com imagem de item nao vira drop de jogo", b["abertas"] == [] and len(b["badges_abertas"]) == 1)


def teste_lembranca():
    print("lembrar (memoria entre rodadas)")
    agora = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    agora_iso = "2026-09-06T12:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        arq = os.path.join(tmp, "conhecidas.json")
        original = checker.CONHECIDAS_ARQ
        checker.CONHECIDAS_ARQ = arq
        try:
            viva = _camp(CIV_ABERTA)
            fora1, mem = checker.lembrar([viva], agora, agora_iso)
            checa("campanha vista entra", len(fora1) == 1 and fora1[0]["vista_agora"])
            checker.guardar_conhecidas(fora1, mem, agora_iso)
            checa("memoria foi gravada", os.path.exists(arq))

            depois = agora + datetime.timedelta(hours=2)
            fora2, mem2 = checker.lembrar([], depois, "2026-09-06T14:00:00Z")
            checker.guardar_conhecidas(fora2, mem2, "2026-09-06T14:00:00Z")
            checa("campanha some do ar mas continua no feed", len(fora2) == 1, len(fora2))
            checa("marcada como lembrada", fora2 and fora2[0]["vista_agora"] is False)

            muito_depois = agora + datetime.timedelta(hours=30)
            fora3, _m = checker.lembrar([], muito_depois, "2026-09-07T18:00:00Z")
            checa("depois de 24h sem ver, esquece", fora3 == [], fora3)

            # A memoria da regra ANTIGA nao pode voltar: Apex "aberto" gravado
            # ontem (formato antigo, sem tipo_premio) e campanha fechada. Badge
            # aberta e drop de sub CONTINUAM: desde 06/09 valem live.
            velha_apex = dict(_camp(APEX_FECHADA), visto_em=agora_iso)
            velha_apex["availability"] = "open"; velha_apex.pop("tipo_premio")   # formato antigo
            badge = dict(_camp(ONIMUSHA_BADGE_ABERTA), visto_em=agora_iso)
            sub = dict(_camp(DELTA_SUB), visto_em=agora_iso)
            fechada = dict(_camp(APEX_FECHADA), visto_em=agora_iso)
            json.dump({"campanhas": {"a": velha_apex, "b": badge, "c": sub, "d": fechada}},
                      io.open(arq, "w", encoding="utf-8"))
            fora4, mem4 = checker.lembrar([], agora, agora_iso)
            checa("formato antigo e fechada sao purgados; badge e sub ficam",
                  sorted(c["name"] for c in fora4) == ["ANNIVERSARY PREVIEW SUB", "Onimusha Armament"]
                  and sorted(mem4) == ["b", "c"], (sorted(c["name"] for c in fora4), sorted(mem4)))

            json.dump({"campanhas": {"velha": dict(_camp(CIV_ABERTA), end_at="2026-09-05T00:00:00Z",
                                                   visto_em=agora_iso)}}, io.open(arq, "w", encoding="utf-8"))
            fora5, _m = checker.lembrar([], agora, agora_iso)
            checa("campanha expirada nao volta", fora5 == [], fora5)
        finally:
            checker.CONHECIDAS_ARQ = original


def teste_jogo_da_campanha():
    print("jogo da campanha x categoria do canal")
    c = dict(MINECRAFT_BADGE, game={"id": "509663", "name": "Special Events"})
    jogo, capa, _s = checker._jogo_da_campanha(c, "Just Chatting", "capa.jpg", "just")
    checa("manda o jogo da campanha", jogo == "Special Events", jogo)
    checa("sem capa quando o jogo nao e o da categoria", capa is None)
    jogo2, capa2, _s = checker._jogo_da_campanha(SEM_ALLOW, "GunZ: The Duel", "capa.jpg", "gunz")
    checa("sem game na campanha fica a categoria", jogo2 == "GunZ: The Duel" and capa2 == "capa.jpg")


def teste_jogos_fora():
    print("jogos-fora")
    fora = ["blackdesert", "metin2"]
    checa("casa por trecho", checker.esta_fora("Black Desert Online", fora))
    checa("ignora pontuacao e espaco", checker.esta_fora("Metin 2", fora))
    checa("nao barra quem nao esta", not checker.esta_fora("Path of Exile 2", fora))
    checa("nome vazio nao barra", not checker.esta_fora("", fora))


def teste_coletar_nao_quebrou_o_alerta():
    print("interface que o alerta_drops e o drops_tray usam")
    import inspect
    checa("coletar aceita incluir_badges", "incluir_badges" in inspect.signature(checker.coletar).parameters)
    checa("varrer existe pra varredura", callable(getattr(checker, "varrer", None)))
    original = checker.fetch
    checker.fetch = lambda url, as_json=True: {"campaigns": [{"game": "X"}], "badges": [{"title": "b"}],
                                                "error": None, "updated_at": "2026-09-06T12:00:00Z"}
    try:
        col = checker.coletar(incluir_badges=False)
    finally:
        checker.fetch = original
    for chave in ("camps", "badges", "fechadas", "erros", "source_updated"):
        checa("devolve a chave %s" % chave, chave in col)
    checa("incluir_badges=False zera as badges", col["badges"] == [])


def _com_twitch_fingida(respostas_por_canal, corpo):
    """Roda main() com a Twitch trocada por respostas fixas; devolve o feed."""
    orig = (tw.top_categorias, tw.categorias_quentes, tw.categoria_com_canais, tw.campanhas_do_canal,
            checker.write, checker.carrega_badges, checker.carrega_fora,
            checker.CONHECIDAS_ARQ, checker.VIGIADAS_ARQ)
    saida = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            tw.top_categorias = lambda n=30: [("Jogo", 10)]
            tw.categorias_quentes = lambda: []
            tw.categoria_com_canais = lambda nome, limite=100: {
                "id": "1", "nome": nome, "slug": "j", "capa": "c.jpg", "viewers": 10,
                "canais": [("i%d" % i, "c%d" % i, 10 - i) for i in range(len(respostas_por_canal))]}
            fila = dict(respostas_por_canal)
            def responde(cid):
                r = fila.get(cid)
                if isinstance(r, Exception):
                    raise r
                return r or []
            tw.campanhas_do_canal = responde
            checker.carrega_badges = lambda agora: []
            checker.carrega_fora = lambda: []
            checker.CONHECIDAS_ARQ = os.path.join(tmp, "conhecidas.json")
            checker.VIGIADAS_ARQ = os.path.join(tmp, "vigiadas.json")
            checker.write = lambda r: saida.update(r)
            corpo()
        finally:
            (tw.top_categorias, tw.categorias_quentes, tw.categoria_com_canais, tw.campanhas_do_canal,
             checker.write, checker.carrega_badges, checker.carrega_fora,
             checker.CONHECIDAS_ARQ, checker.VIGIADAS_ARQ) = orig
    return saida


def teste_rodada_inteira():
    """main() de ponta a ponta: o que a Twitch responde -> o que o feed publica."""
    print("rodada inteira (main) com respostas fingidas")
    saida = _com_twitch_fingida(
        {"i0": [CIV_ABERTA, APEX_FECHADA], "i1": [ONIMUSHA_BADGE_ABERTA, MINECRAFT_BADGE, DELTA_SUB]},
        checker.main)
    jogos = [(c["game"], c["reward_type"]) for c in saida.get("campaigns") or []]
    checa("feed ok", saida.get("ok") is True, saida.get("error"))
    checa("publica Civ e Delta (sub, marcado) como game e Onimusha como platform; Apex e Minecraft fora",
          jogos == [("Delta Force", "game"), ("Sid Meier's Civilization VII", "game"),
                    ("Onimusha: Way of the Sword", "platform")], jogos)   # ordem: quem acaba antes
    c = saida["counts"]
    checa("contou o Apex como so-canais-escolhidos", c.get("so_canais_escolhidos") == 1, c)
    checa("contou a badge de canal e o drop de sub publicado", c.get("badges_de_canal") == 1 and c.get("so_sub") == 1, c)
    checa("game_drops=2 platform=1", c.get("game_drops") == 2 and c.get("platform") == 1, c)


def teste_rodada_morta_nao_finge_saude():
    print("persisted query morrendo nao pode sair como ok")
    saida = _com_twitch_fingida({"i0": tw.ErroGQL("PersistedQueryNotFound"),
                                 "i1": tw.ErroGQL("PersistedQueryNotFound")}, checker.main)
    checa("feed sai marcado como NAO ok", saida.get("ok") is False, saida.get("ok"))
    checa("e diz o porque", bool(saida.get("error")), saida.get("error"))


def testes_ao_vivo():
    print("\n=== AO VIVO (fala com a Twitch) ===")
    top = tw.top_categorias(5)
    checa("a Twitch devolveu categorias", len(top) >= 3, top)
    info = tw.categoria_com_canais("Just Chatting", limite=5)
    checa("categoria existe", info is not None and info.get("id"))
    checa("veio capa do jogo", bool(info and info.get("capa")))
    checa("jogo inventado devolve None", tw.categoria_com_canais("Jogo Que Nao Existe 9z9z") is None)
    # a query crua responde allow e distributionType pra um canal ao vivo com drop
    quentes = tw.categorias_quentes()
    achou = False
    for cat in quentes[:6]:
        i = tw.categoria_com_canais(cat, limite=3)
        for cid, _login, _v in (i or {}).get("canais") or []:
            for camp in tw.campanhas_do_canal(cid):
                if isinstance(camp.get("allow"), dict) and camp.get("timeBasedDrops"):
                    achou = True
                    break
            if achou:
                break
        if achou:
            break
    checa("campanha ao vivo veio com `allow` e drops", achou)


def main():
    teste_tipo_da_campanha()
    teste_aberta_e_permitidos()
    teste_sub_e_minutos()
    teste_formato_do_feed()
    teste_peneira()
    teste_regressoes()
    teste_lembranca()
    teste_jogo_da_campanha()
    teste_jogos_fora()
    teste_coletar_nao_quebrou_o_alerta()
    teste_rodada_inteira()
    teste_rodada_morta_nao_finge_saude()
    if "--ao-vivo" in sys.argv:
        testes_ao_vivo()
    print()
    if FALHAS:
        print("FALHARAM %d: %s" % (len(FALHAS), ", ".join(FALHAS)))
        return 1
    print("todos passaram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
