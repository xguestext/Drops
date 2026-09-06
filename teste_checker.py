#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do radar. Rode com: python teste_checker.py

Os de baixo NAO tocam a rede: sao respostas REAIS da Twitch capturadas em
06/09/2026, inclusive as do incidente do Minecraft. Servem pra garantir que a
peneira continua separando drop de verdade de badge de canal mesmo depois de
alguem mexer no codigo.

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

# O que os canais de Minecraft respondiam na hora em que o piloto abriu a live:
# badge do proprio streamer, um canal cada.
MINECRAFT_BADGE = {
    "id": "e229e5fc-69b3-474a-9845-ba97b1539a97",
    "name": "LACY X MARLON MARATHON",
    "game": None,
    "detailsURL": "",
    "startAt": "2026-09-01T19:00:00Z",
    "endAt": "2026-09-12T19:00:00Z",
    "imageURL": "https://static-cdn.jtvnw.net/badges/v1/983f4bdc/3",
    "timeBasedDrops": [{
        "requiredMinutesWatched": 0,
        "benefitEdges": [{"benefit": {
            "name": "LACY X MARLON MARATHON",
            "imageAssetURL": "https://static-cdn.jtvnw.net/badges/v1/983f4bdc/3"}}],
    }],
}

# O drop de verdade do mesmo dia: item de jogo, a mesma campanha em 7 canais.
GUNZ_ITEM = {
    "id": "b3bf7ef1-3d9a-4438-8ef9-9fd6f8e92e26",
    "name": "Global Launch Welcome Kit",
    "game": None,
    "detailsURL": "https://gz.ludenus.com/drops",
    "startAt": "2026-08-12T00:00:00Z",
    "endAt": "2036-09-08T05:59:59.999Z",
    "imageURL": "https://static-cdn.jtvnw.net/twitch-quests-assets/CAMPAIGN/db6c48c9.jpeg",
    "timeBasedDrops": [{
        "requiredMinutesWatched": 120,
        "benefitEdges": [{"benefit": {
            "name": "Global Launch Drops Kit",
            "imageAssetURL": "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/5ddbd64a.jpeg"}}],
    }],
}

# Campanha com dois degraus (o segundo e o que vale): 0 min e 360 min.
DOIS_DEGRAUS = {
    "id": "dois-degraus", "name": "Duas etapas", "detailsURL": "", "imageURL": "",
    "startAt": None, "endAt": None,
    "timeBasedDrops": [
        {"requiredMinutesWatched": 0, "benefitEdges": [{"benefit": {
            "name": "Entrada", "imageAssetURL":
            "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/a.png"}}]},
        {"requiredMinutesWatched": 360, "benefitEdges": [{"benefit": {
            "name": "Premio", "imageAssetURL":
            "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/b.png"}}]},
    ],
}


def teste_tipo_da_campanha():
    print("tipo_da_campanha")
    checa("badge de canal e badge", tw.tipo_da_campanha(MINECRAFT_BADGE) == "badge",
          tw.tipo_da_campanha(MINECRAFT_BADGE))
    checa("item de jogo e game", tw.tipo_da_campanha(GUNZ_ITEM) == "game",
          tw.tipo_da_campanha(GUNZ_ITEM))
    checa("campanha sem premio nenhum nao vira game",
          tw.tipo_da_campanha({"timeBasedDrops": [], "imageURL": ""}) != "game")
    # Premio misturado (item + badge no mesmo drop) conta como item: o item e o
    # que interessa e e o que se pode farmar.
    misto = copy.deepcopy(GUNZ_ITEM)
    misto["timeBasedDrops"][0]["benefitEdges"].append(
        {"benefit": {"name": "Badge", "imageAssetURL":
                     "https://static-cdn.jtvnw.net/badges/v1/x/3"}})
    checa("item + badge continua game", tw.tipo_da_campanha(misto) == "game")


def teste_minutos():
    print("minutos_de")
    checa("pega o menor watch de verdade", tw.minutos_de(DOIS_DEGRAUS) == 360,
          tw.minutos_de(DOIS_DEGRAUS))
    checa("120 quando so ha um degrau", tw.minutos_de(GUNZ_ITEM) == 120)
    checa("0 quando a campanha nao pede tempo", tw.minutos_de(MINECRAFT_BADGE) == 0)
    checa("nao explode com lista vazia", tw.minutos_de({}) == 0)


def teste_amostra():
    print("amostra_de_canais")
    canais = [("i%d" % i, "c%d" % i, i) for i in range(20)]
    a = tw.amostra_de_canais(canais, 8)
    vistos = [v for _i, _l, v in a]
    checa("pega 8", len(a) == 8, len(a))
    checa("tem canal grande", max(vistos) == 19, vistos)
    checa("tem canal pequeno", min(vistos) == 0, vistos)
    poucos = canais[:3]
    checa("com poucos canais devolve todos", len(tw.amostra_de_canais(poucos, 8)) == 3)
    checa("lista vazia nao explode", tw.amostra_de_canais([], 8) == [])


def _camp(nome, jogo, tipo="game", canais=2, fim="2036-01-01T00:00:00Z"):
    c = checker._campanha_vazia(
        GUNZ_ITEM if tipo == "game" else MINECRAFT_BADGE, jogo, "capa.jpg", "slug")
    c["id"] = nome
    c["name"] = nome
    c["end_at"] = fim
    c["canais_vistos"] = ["canal%d" % i for i in range(canais)]
    c["canais_perguntados"] = 6
    return c


def teste_peneira():
    print("peneirar")
    campanhas = [
        _camp("drop bom", "Path of Exile 2", "game", canais=6),
        _camp("so um canal", "Apex Legends", "game", canais=1),
        _camp("badge de canal", "Minecraft", "badge", canais=1),
        _camp("badge em varios", "VALORANT", "badge", canais=5),
        _camp("jogo barrado", "Fortnite", "game", canais=6),
    ]
    abertas, de_canal, barradas, fora = checker.peneirar(campanhas, ["fortnite"])
    nomes = [c["name"] for c in abertas]
    checa("drop bom passa", nomes == ["drop bom"], nomes)
    checa("badge fica de fora", len(de_canal) == 2, len(de_canal))
    checa("item de um canal so fica de fora", [c["name"] for c in barradas] == ["so um canal"])
    checa("jogos-fora manda", [c["name"] for c in fora] == ["jogo barrado"])


def teste_regressao_minecraft():
    """O incidente de 06/09: NADA do que o Minecraft tinha pode virar drop."""
    print("regressao do Minecraft (06/09/2026)")
    # As 6 campanhas que os canais de Minecraft realmente respondiam: todas
    # badge, todas de um canal so.
    vistas = []
    for i in range(6):
        c = copy.deepcopy(MINECRAFT_BADGE)
        c["id"] = "badge-%d" % i
        campanha = checker._campanha_vazia(c, "Minecraft", "capa.jpg", "minecraft")
        campanha["canais_vistos"] = ["streamer%d" % i]
        vistas.append(campanha)
    abertas, _de_canal, _barradas, _fora = checker.peneirar(vistas, [])
    checa("Minecraft nao produz NENHUMA campanha", abertas == [], [c["name"] for c in abertas])


def teste_lembranca():
    print("lembrar (memoria entre rodadas)")
    agora = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    agora_iso = "2026-09-06T12:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        arq = os.path.join(tmp, "conhecidas.json")
        original = checker.CONHECIDAS_ARQ
        checker.CONHECIDAS_ARQ = arq
        try:
            viva = _camp("viva", "Dead by Daylight", canais=6)
            fora1, mem = checker.lembrar([viva], agora, agora_iso)
            checa("campanha vista entra", len(fora1) == 1 and fora1[0]["vista_agora"])
            # quem grava e o guardar_conhecidas, DEPOIS da prova de abertura
            checker.guardar_conhecidas(fora1, mem, agora_iso)
            checa("memoria foi gravada", os.path.exists(arq))

            # Rodada seguinte: ninguem ao vivo naquele jogo, mas a campanha vale.
            depois = agora + datetime.timedelta(hours=2)
            fora2, mem2 = checker.lembrar([], depois, "2026-09-06T14:00:00Z")
            checker.guardar_conhecidas(fora2, mem2, "2026-09-06T14:00:00Z")
            checa("campanha some do ar mas continua no feed", len(fora2) == 1, len(fora2))
            checa("marcada como lembrada", fora2 and fora2[0]["vista_agora"] is False)

            # Passou o prazo de lembranca.
            muito_depois = agora + datetime.timedelta(hours=30)
            fora3, _m3 = checker.lembrar([], muito_depois, "2026-09-07T18:00:00Z")
            checa("depois de 24h sem ver, esquece", fora3 == [], fora3)

            # Campanha que ja acabou nao volta nunca.
            json.dump({"campanhas": {"velha": dict(_camp("velha", "X"),
                                                  end_at="2026-09-05T00:00:00Z",
                                                  visto_em=agora_iso)}},
                      open(arq, "w", encoding="utf-8"))
            fora4, _mem = checker.lembrar([], agora, agora_iso)
            checa("campanha expirada nao volta", fora4 == [], fora4)
        finally:
            checker.CONHECIDAS_ARQ = original


def teste_prova_de_abertura():
    """Campanha de evento (so canais convidados) tem que cair aqui."""
    print("prova de abertura (canal comum tambem ganha?)")
    orig_comuns, orig_camps = tw.canais_comuns, tw.campanhas_do_canal
    try:
        por_cat = {"League of Legends": {"nome": "League of Legends", "id": "21779"}}

        # 1) ninguem comum ganha -> reprovada
        tw.canais_comuns = lambda nome, limite=30: [
            {"id": str(i), "login": "c%d" % i, "viewers": 100, "afiliado": True,
             "parceiro": False, "marcado": False} for i in range(6)]
        tw.campanhas_do_canal = lambda cid: [{"id": "outra"}]
        c = _camp("Sub Drop", "League of Legends", canais=4)
        ok, fora = checker.provar_abertura([c], por_cat, {})
        checa("campanha de convidados e reprovada", not ok and len(fora) == 1)
        checa("e o motivo fica gravado", fora and fora[0]["prova"] == "so convidados")

        # 2) um canal comum ganha -> aprovada
        tw.campanhas_do_canal = lambda cid: [{"id": "Sub Drop"}]
        c2 = _camp("Sub Drop", "League of Legends", canais=4)
        ok2, fora2 = checker.provar_abertura([c2], por_cat, {})
        checa("campanha que qualquer um ganha passa", len(ok2) == 1 and not fora2)
        checa("marcada como aberta", ok2[0]["prova"] == "aberta")

        # 3) poucos canais pra perguntar -> NAO condena (falha aberto)
        tw.canais_comuns = lambda nome, limite=30: [
            {"id": "1", "login": "unico", "viewers": 9, "afiliado": True,
             "parceiro": False, "marcado": False}]
        tw.campanhas_do_canal = lambda cid: []
        c3 = _camp("Sub Drop", "League of Legends", canais=4)
        ok3, fora3 = checker.provar_abertura([c3], por_cat, {})
        checa("sem gente pra testar, nao reprova", len(ok3) == 1 and not fora3)
        checa("fica marcada como nao conferida", ok3[0]["prova"] == "nao deu pra conferir")

        # 4) a Twitch fora do ar tambem nao condena
        def explode(nome, limite=30):
            raise tw.ErroGQL("timeout")
        tw.canais_comuns = explode
        c4 = _camp("Sub Drop", "League of Legends", canais=4)
        ok4, fora4 = checker.provar_abertura([c4], por_cat, {})
        checa("erro de rede nao reprova campanha", len(ok4) == 1 and not fora4)

        # 5) resultado guardado nao repergunta
        chamou = {"n": 0}
        def conta(nome, limite=30):
            chamou["n"] += 1
            return []
        tw.canais_comuns = conta
        c5 = _camp("Sub Drop", "League of Legends", canais=4)
        memoria = {c5["id"]: {"prova": "so convidados"}}
        ok5, fora5 = checker.provar_abertura([c5], por_cat, memoria)
        checa("usa o que ja sabia, sem perguntar de novo",
              chamou["n"] == 0 and len(fora5) == 1, chamou["n"])
    finally:
        tw.canais_comuns, tw.campanhas_do_canal = orig_comuns, orig_camps


def teste_jogos_fora():
    print("jogos-fora")
    fora = ["blackdesert", "metin2"]
    checa("casa por trecho", checker.esta_fora("Black Desert Online", fora))
    checa("ignora pontuacao e espaco", checker.esta_fora("Metin 2", fora))
    checa("nao barra quem nao esta", not checker.esta_fora("Path of Exile 2", fora))
    checa("nome vazio nao barra", not checker.esta_fora("", fora))


def teste_formato_do_feed():
    """O bot e o site leem campos com nome fixo — nao podem sumir."""
    print("formato que o bot e o site esperam")
    c = _camp("x", "Path of Exile 2", canais=3)
    for campo in ("id", "name", "status", "start_at", "end_at", "game", "game_box",
                  "availability", "required_minutes", "reward_type", "rewards",
                  "image", "details_url", "src", "channels"):
        checa("campo %s existe" % campo, campo in c)
    checa("availability e open", c["availability"] == "open")
    checa("reward_type e game", c["reward_type"] == "game")
    checa("src diz de onde veio", c["src"] == "twitch-gql")
    checa("rewards tem nome e minutos",
          bool(c["rewards"]) and "name" in c["rewards"][0] and "minutes" in c["rewards"][0])


def teste_jogo_da_campanha():
    """O jogo e o da CAMPANHA; a categoria e so o plano B."""
    print("jogo da campanha x categoria do canal")
    c = dict(MINECRAFT_BADGE, game={"id": "509663", "name": "Special Events"})
    jogo, capa, slug = checker._jogo_da_campanha(c, "Just Chatting", "capa.jpg", "just")
    checa("manda o jogo da campanha", jogo == "Special Events", jogo)
    checa("sem capa quando o jogo nao e o da categoria", capa is None, capa)
    jogo2, capa2, _s = checker._jogo_da_campanha(GUNZ_ITEM, "GunZ: The Duel", "capa.jpg", "gunz")
    checa("sem game na campanha fica a categoria", jogo2 == "GunZ: The Duel", jogo2)
    checa("e a capa da categoria continua", capa2 == "capa.jpg")
    c3 = dict(GUNZ_ITEM, game={"id": "1", "name": "GunZ The Duel"})
    jogo3, capa3, _s = checker._jogo_da_campanha(c3, "GunZ: The Duel", "capa.jpg", "gunz")
    checa("mesmo jogo escrito diferente mantem a capa", capa3 == "capa.jpg", jogo3)


def teste_jogo_pequeno():
    """Categoria com UM canal no mundo nao pode provar 2 canais."""
    print("drop de jogo pequeno (1 canal no ar)")
    so_um = _camp("B&S NEO Reignited Drops", "Blade & Soul NEO", canais=1)
    so_um["canais_na_categoria"] = 1
    so_um["canais_perguntados"] = 1
    so_um["campanha_do_jogo"] = True
    abertas, _dc, barradas, _f = checker.peneirar([so_um], [])
    checa("drop do jogo pequeno passa", [c["name"] for c in abertas] == ["B&S NEO Reignited Drops"],
          [c["name"] for c in barradas])

    # Havia outros canais e so um entregou: campanha de convidado (evento).
    convidado = _camp("ZEVENT 2026", "ZEVENT", canais=1)
    convidado["canais_na_categoria"] = 40
    convidado["canais_perguntados"] = 6
    convidado["campanha_do_jogo"] = True
    _a, _dc, barradas2, _f = checker.peneirar([convidado], [])
    checa("campanha de convidado continua barrada",
          [c["name"] for c in barradas2] == ["ZEVENT 2026"])

    # Um canal so, mas a campanha e de OUTRO jogo: campanha do canal.
    do_canal = _camp("Ironmouse Subathon", "Kingdom Hearts", canais=1)
    do_canal["canais_na_categoria"] = 1
    do_canal["canais_perguntados"] = 1
    do_canal["campanha_do_jogo"] = False
    _a, _dc, barradas3, _f = checker.peneirar([do_canal], [])
    checa("campanha de canal (jogo diferente) continua barrada",
          [c["name"] for c in barradas3] == ["Ironmouse Subathon"])


def teste_juntar_canais():
    """Dois canais em rodadas diferentes valem como dois canais."""
    print("memoria de canais entre rodadas")
    agora = datetime.datetime(2026, 9, 6, 12, 0, tzinfo=datetime.timezone.utc)
    agora_iso = "2026-09-06T12:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        original = checker.CANAIS_ARQ
        checker.CANAIS_ARQ = os.path.join(tmp, "canais.json")
        try:
            r1 = _camp("drop pequeno", "Jogo Pequeno", canais=1)
            r1["canais_vistos"] = ["streamer_a"]
            checker.juntar_canais([r1], agora, agora_iso)
            checa("primeira rodada nao inventa canal", len(r1["canais_vistos"]) == 1)

            r2 = _camp("drop pequeno", "Jogo Pequeno", canais=1)
            r2["canais_vistos"] = ["streamer_b"]
            checker.juntar_canais([r2], agora, "2026-09-06T12:30:00Z")
            checa("segunda rodada soma o canal da primeira",
                  sorted(r2["canais_vistos"]) == ["streamer_a", "streamer_b"], r2["canais_vistos"])
            abertas, _dc, _b, _f = checker.peneirar([r2], [])
            checa("e ai a campanha passa na peneira", len(abertas) == 1)

            # Badge nao entra na memoria: ela nunca depende de contagem.
            b = _camp("badge", "Jogo Pequeno", tipo="badge", canais=1)
            b["canais_vistos"] = ["streamer_c"]
            checker.juntar_canais([b], agora, agora_iso)
            guardado = json.load(io.open(checker.CANAIS_ARQ, encoding="utf-8"))["campanhas"]
            checa("badge fica de fora da memoria de canais", "badge" not in guardado,
                  list(guardado))
        finally:
            checker.CANAIS_ARQ = original


def teste_coletar_nao_quebrou_o_alerta():
    """`coletar` e a interface do alerta e da bandeja do dono — nao pode mudar."""
    print("interface que o alerta_drops e o drops_tray usam")
    import inspect
    par = inspect.signature(checker.coletar).parameters
    checa("coletar aceita incluir_badges", "incluir_badges" in par, list(par))
    checa("varrer existe pra varredura", callable(getattr(checker, "varrer", None)))
    # sem rede: so confere que as chaves saem do que o feed traz
    original = checker.fetch
    checker.fetch = lambda url, as_json=True: {
        "campaigns": [{"game": "X"}], "badges": [{"title": "b"}], "error": None,
        "updated_at": "2026-09-06T12:00:00Z"}
    try:
        col = checker.coletar(incluir_badges=False)
    finally:
        checker.fetch = original
    for chave in ("camps", "badges", "fechadas", "erros", "source_updated"):
        checa("devolve a chave %s" % chave, chave in col)
    checa("camps sao as campanhas do feed", col["camps"] == [{"game": "X"}])
    checa("incluir_badges=False zera as badges", col["badges"] == [])


def teste_rodada_morta_nao_finge_saude():
    """Se ninguem respondeu sobre campanha, o feed tem que dizer que falhou."""
    print("persisted query morrendo nao pode sair como ok")
    class _Erro(Exception):
        pass
    orig_cat, orig_camp, orig_top, orig_quentes = (
        tw.categoria_com_canais, tw.campanhas_do_canal, tw.top_categorias, tw.categorias_quentes)
    orig_write, orig_badges, orig_conhec, orig_canais = (
        checker.write, checker.carrega_badges, checker.CONHECIDAS_ARQ, checker.CANAIS_ARQ)
    saida = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            tw.top_categorias = lambda n=30: [("Jogo", 10)]
            tw.categorias_quentes = lambda: []
            tw.categoria_com_canais = lambda nome, limite=100: {
                "id": "1", "nome": nome, "slug": "j", "capa": "c.jpg", "viewers": 10,
                "canais": [("i1", "c1", 5), ("i2", "c2", 4)]}
            def explode(cid):
                raise tw.ErroGQL("PersistedQueryNotFound")
            tw.campanhas_do_canal = explode
            checker.carrega_badges = lambda agora: []
            checker.CONHECIDAS_ARQ = os.path.join(tmp, "conhecidas.json")
            checker.CANAIS_ARQ = os.path.join(tmp, "canais.json")
            checker.write = lambda r: saida.update(r)
            checker.main()
        finally:
            (tw.categoria_com_canais, tw.campanhas_do_canal, tw.top_categorias,
             tw.categorias_quentes) = orig_cat, orig_camp, orig_top, orig_quentes
            (checker.write, checker.carrega_badges, checker.CONHECIDAS_ARQ,
             checker.CANAIS_ARQ) = orig_write, orig_badges, orig_conhec, orig_canais
    checa("feed sai marcado como NAO ok", saida.get("ok") is False, saida.get("ok"))
    checa("e diz o porque", bool(saida.get("error")), saida.get("error"))


def testes_ao_vivo():
    print("\n=== AO VIVO (fala com a Twitch) ===")
    print("categorias do topo")
    top = tw.top_categorias(5)
    checa("a Twitch devolveu categorias", len(top) >= 3, top)

    print("uma categoria e seus canais com drop")
    info = tw.categoria_com_canais("Just Chatting", limite=5)
    checa("categoria existe", info is not None and info.get("id"))
    checa("veio capa do jogo", bool(info and info.get("capa")))

    print("categoria que nao existe")
    checa("jogo inventado devolve None",
          tw.categoria_com_canais("Jogo Que Nao Existe 9z9z") is None)

    print("campanhas de um canal fora do ar")
    cid, _jogo = tw.id_do_canal("twitch")
    checa("achou o id do canal", bool(cid))


def main():
    teste_tipo_da_campanha()
    teste_minutos()
    teste_amostra()
    teste_peneira()
    teste_regressao_minecraft()
    teste_lembranca()
    teste_jogos_fora()
    teste_formato_do_feed()
    teste_jogo_da_campanha()
    teste_jogo_pequeno()
    teste_juntar_canais()
    teste_prova_de_abertura()
    teste_coletar_nao_quebrou_o_alerta()
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
