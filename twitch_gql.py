#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cliente da GQL publica da Twitch — a UNICA fonte de drops do radar.

POR QUE ISTO EXISTE (06/09/2026)
  Ate hoje o radar somava tres agregadores de terceiros. Um deles
  (twitchdrops.app, que e raspagem de HTML) publicou "Minecraft — Amethyst
  Drone". O piloto acreditou, abriu live na Misaune e anunciou 61 operarios
  pra 1 pessoa real. Perguntada DIRETO, a Twitch respondeu outra coisa: os 13
  canais de Minecraft marcados com DropsEnabled naquele momento tinham todos
  campanha de BADGE DO PROPRIO CANAL (aniversario, subathon), e o canal da
  Misaune, ao vivo na categoria, nao tinha campanha nenhuma.
  Entao paramos de perguntar pra intermediario. Quem responde e a Twitch.

O QUE A TWITCH RESPONDE SEM LOGIN NENHUM
  games(first:30, options:{sort:VIEWER_COUNT})                 -> categorias do momento
  streams(first:30, options:{systemFilters:[DROPS_ENABLED]})   -> quem esta com drop AGORA
  game(name:X){ streams(options:{systemFilters:[DROPS_ENABLED]}) }
                                                               -> os canais com drop daquela categoria
  channel(id:X){ viewerDropCampaigns { ... allow ... distributionType ... } }
                                                               -> AS CAMPANHAS DE VERDADE do canal, com
                                                                  QUEM PODE (allow) e O QUE E o premio

O QUE ELA NAO RESPONDE — e por isso o desenho e este
  Paginacao (`after:`) e `dropCampaign(id:)` pedem o token de integridade que
  so o navegador de verdade produz (testado em 06/09: o /integrity solto
  devolve token, e a Twitch recusa esse token). Ou seja: NAO existe "me da a
  lista de todas as campanhas". A lista e montada perguntando canal a canal —
  e e por isso que ela nao tem como vir errada: cada campanha aqui foi vista
  na resposta de um canal real, ao vivo, naquele minuto.

COMO SE SEPARA O QUE INTERESSA (tudo campo da propria campanha, 06/09/2026)
  ABERTA x FECHADA: `allow`. `isEnabled: false` = qualquer canal ao vivo na
    categoria da o drop (na pagina da Twitch: "Go to a participating live
    channel"). `isEnabled: true` + lista de canais = so aqueles canais ganham
    (na pagina: "including playapex, NiceWigg, algs1_team1... and more"). O ALGS
    do Apex tinha 161 canais escolhidos e o ZEVENT 338 — os dois passaram na
    peneira antiga por aparecerem em varios canais. Amostragem nao prova
    abertura; a lista de permitidos prova.
  DROP x BADGE: `benefit.distributionType`. DIRECT_ENTITLEMENT = item de jogo
    (o selo "IN-GAME ITEM" da pagina). BADGE = badge da Twitch (fotinha do chat)
    — e a Twitch serve a imagem de badge de campanha da MESMA pasta dos itens
    (/twitch-quests-assets/REWARD/), entao a pasta da imagem NAO separa os dois:
    Onimusha Armament, Sorcerer Rogier (ELDEN RING) e Dawnwalker Launch sao
    BADGE com imagem em REWARD. A pasta so vale como plano B quando o campo
    nao veio.
  FARMAVEL: `requiredSubs`. Drop que exige sub ("Split 3 - Sub Drop", "ANNIVERSARY
    PREVIEW SUB") nao se ganha assistindo — fica de fora.
"""
import json
import time
import urllib.request
import urllib.error

# Client-Id publico do site da Twitch. E o mesmo que o navegador de qualquer
# pessoa manda ao abrir twitch.tv — nao e credencial de conta, nao identifica
# ninguem e nao da acesso a nada privado.
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
GQL = "https://gql.twitch.tv/gql"

# O que se pede de cada campanha, e quem usa cada campo:
#   allow             -> aberta a todos ou so canais escolhidos (o caso do Apex ALGS)
#   distributionType  -> item de jogo (DIRECT_ENTITLEMENT) x badge da Twitch (BADGE)
#   requiredSubs      -> drop de sub nao se farma assistindo
#   startAt/endAt     -> janela da campanha (o bot recusa campanha sem hora de inicio)
#   owner/description -> so pro site mostrar de quem e e o que promete
# `self { ... }` e eventBasedDrops ficam de fora: exigem login e derrubam a query
# inteira com "server error".
CAMPOS_CAMPANHA = (
    "id name status startAt endAt imageURL detailsURL accountLinkURL description "
    "owner { id name } game { id name displayName boxArtURL } "
    "allow { isEnabled channels { id name } } "
    "timeBasedDrops { id name startAt endAt requiredMinutesWatched requiredSubs "
    "benefitEdges { entitlementLimit benefit { id name imageAssetURL distributionType } } }"
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) drops-radar/3.0"
TIMEOUT = 25
# Respiro entre uma pergunta e outra. Sao ~310 por rodada saindo do mesmo IP do
# runner; medido em 06/09 nao tomamos um 429 sequer, mas 60ms custam 20s no
# total e tiram a gente da faixa de "rajada".
PAUSA_S = 0.06

# Pastas de imagem — PLANO B, so quando a resposta nao traz distributionType.
PREFIXO_ITEM = "/twitch-quests-assets/REWARD/"
PREFIXO_BADGE = "/badges/"


class ErroGQL(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# TRANSPORTE
# ─────────────────────────────────────────────────────────────────────────────

def _post(corpo, tentativas=3):
    """Uma chamada na GQL. Erro de rede tenta de novo; erro de logica, nao.

    Falha DEVOLVENDO EXCECAO de proposito: quem chama tem que decidir se o
    ciclo inteiro fracassa (e o feed antigo fica no ar) ou se aquela categoria
    apenas fica de fora. Silenciar aqui era como o radar publicava lista curta
    fingindo estar completa.
    """
    dado = json.dumps(corpo).encode("utf-8")
    ultima = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(GQL, data=dado, headers={
                "Client-Id": CLIENT_ID,
                "Content-Type": "application/json",
                "User-Agent": UA,
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                corpo_resp = json.loads(r.read().decode("utf-8"))
            time.sleep(PAUSA_S)
            return corpo_resp
        except urllib.error.HTTPError as e:
            ultima = "HTTP %s" % e.code
            # 429/5xx e passageiro; 4xx de verdade nao melhora tentando de novo.
            if e.code not in (429, 500, 502, 503, 504):
                break
        except Exception as e:                                  # rede, timeout
            ultima = str(e)
        if i < tentativas - 1:
            time.sleep(1.5 * (i + 1))
    raise ErroGQL(ultima or "sem resposta")


def consulta(texto):
    """Query GraphQL crua. Devolve o `data` ou levanta ErroGQL."""
    d = _post({"query": texto})
    if d.get("errors"):
        raise ErroGQL(json.dumps(d["errors"], ensure_ascii=False)[:200])
    return d.get("data") or {}


def _txt(s):
    """String pro meio da query, escapada pelo proprio json (aspas, acento)."""
    return json.dumps(s or "", ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# PERGUNTAS
# ─────────────────────────────────────────────────────────────────────────────

def top_categorias(n=30):
    """As categorias mais assistidas agora. (nome, viewers)

    Serve so pra descobrir onde procurar: uma campanha nova quase sempre nasce
    numa categoria que subiu de publico.
    """
    d = consulta('{ games(first: %d, options: {sort: VIEWER_COUNT}) '
                 '{ edges { node { displayName viewersCount } } } }' % int(n))
    fora = []
    for e in ((d.get("games") or {}).get("edges") or []):
        no = (e or {}).get("node") or {}
        if no.get("displayName"):
            fora.append((no["displayName"], no.get("viewersCount") or 0))
    return fora


def categorias_quentes():
    """Categorias dos streams que ESTAO com drop agora, em ordem de publico.

    Este e o atalho: em vez de varrer o mundo, a Twitch ja diz quem esta com
    a marca de drops ligada neste minuto.
    """
    d = consulta('{ streams(first: 30, options: {systemFilters: [DROPS_ENABLED]}) '
                 '{ edges { node { game { displayName } } } } }')
    fora = []
    for e in ((d.get("streams") or {}).get("edges") or []):
        g = (((e or {}).get("node") or {}).get("game") or {}).get("displayName")
        if g and g not in fora:
            fora.append(g)
    return fora


def categoria_com_canais(nome, limite=100):
    """A categoria e quem esta nela COM drop ligado. None se nao existe.

    Uma chamada so traz a capa do jogo (que o site mostra) e a lista de canais
    (de quem vamos perguntar as campanhas) — e por isso que varrer 100
    categorias custa 100 chamadas, nao 200.
    """
    d = consulta(
        '{ game(name: %s) { id displayName slug boxArtURL viewersCount '
        'streams(first: %d, options: {systemFilters: [DROPS_ENABLED]}) '
        '{ edges { node { broadcaster { id login } viewersCount } } } } }'
        % (_txt(nome), int(limite)))
    g = d.get("game")
    if not g:
        return None
    canais = []
    for e in ((g.get("streams") or {}).get("edges") or []):
        # `node`/`broadcaster` pode vir NULO: canal que sai do ar no meio da
        # listagem some do edge sem virar erro de GQL. Indexar cru levantava
        # TypeError, que NAO e ErroGQL — passava direto pelo `except` do
        # checker, o passo do Actions morria antes de commitar, e o drops.json
        # ficava congelado se dizendo fresco (o bot so olha `ok`). Canal sem
        # dono a gente nem teria como perguntar: pula SO ele.
        dono = ((e or {}).get("node") or {}).get("broadcaster") or {}
        if not dono.get("id"):
            continue
        canais.append((dono["id"], dono.get("login") or "",
                       (e["node"].get("viewersCount") or 0)))
    return {
        "id": g.get("id"),
        "nome": g.get("displayName") or nome,
        "slug": g.get("slug") or "",
        "capa": (g.get("boxArtURL") or "").replace("{width}x{height}", "120x160"),
        "viewers": g.get("viewersCount") or 0,
        "canais": canais,
    }


def campanhas_do_canal(canal_id):
    """As campanhas que quem assiste este canal ganha — com permissao e premio.

    Query CRUA (nao a persisted do player): e o que deixa pedir `allow`,
    `distributionType` e `requiredSubs`, que a persisted nao devolve. Sem
    login: testado em 06/09, a Twitch responde tudo isso pra qualquer canal
    ao vivo. Canal fora do ar devolve lista vazia — ela so casa campanha com
    canal enquanto ele esta transmitindo na categoria.
    """
    d = consulta('{ channel(id: %s) { viewerDropCampaigns { %s } } }'
                 % (_txt(str(canal_id)), CAMPOS_CAMPANHA))
    return (d.get("channel") or {}).get("viewerDropCampaigns") or []


def id_do_canal(login):
    """login -> id numerico (a query de drops pede o id, nao o nome)."""
    d = consulta('{ user(login: %s) { id login stream { game { displayName } } } }'
                 % _txt(login))
    u = d.get("user")
    if not u:
        return None, None
    jogo = ((u.get("stream") or {}).get("game") or {}).get("displayName")
    return u.get("id"), jogo


# ─────────────────────────────────────────────────────────────────────────────
# LEITURA DAS CAMPANHAS
# ─────────────────────────────────────────────────────────────────────────────

def _premios(camp):
    """[(nome, imagem, minutos, tipo, subs)] de todos os drops por tempo."""
    fora = []
    for t in camp.get("timeBasedDrops") or []:
        minutos = t.get("requiredMinutesWatched")
        subs = t.get("requiredSubs")
        for b in t.get("benefitEdges") or []:
            ben = b.get("benefit") or {}
            fora.append((ben.get("name") or "", ben.get("imageAssetURL") or "",
                         minutos, ben.get("distributionType"), subs))
    return fora


def tipo_da_campanha(camp):
    """"game" (item de jogo), "badge" (badge da Twitch) ou "platform" (outro).

    Pelo `distributionType` do premio, que e o mesmo campo que desenha o selo
    "IN-GAME ITEM" na pagina da Twitch. A pasta da imagem so entra quando o
    campo nao veio: badge de campanha (Onimusha Armament, Sorcerer Rogier) e
    servida da MESMA pasta que item de jogo, entao a imagem sozinha mente.
    """
    tipos = {t for _n, _u, _m, t, _s in _premios(camp) if t}
    if "DIRECT_ENTITLEMENT" in tipos:
        return "game"
    if tipos:
        return "badge" if tipos <= {"BADGE"} else "platform"
    urls = [u for _n, u, _m, _t, _s in _premios(camp) if u]
    if any(PREFIXO_ITEM in u for u in urls):
        return "game"
    if urls and all(PREFIXO_BADGE in u for u in urls):
        return "badge"
    if PREFIXO_BADGE in (camp.get("imageURL") or ""):
        return "badge"
    return "desconhecido"


def aberta_a_todos(camp):
    """Qualquer canal ao vivo na categoria da o drop? True/False; None se nao veio.

    E a resposta do incidente do Apex ALGS: 161 canais escolhidos, e o radar
    dizia "aberta" porque a campanha aparecia em varios deles. `allow.isEnabled`
    e a Twitch dizendo, com todas as letras, que existe lista de convidados.
    """
    al = camp.get("allow")
    if not isinstance(al, dict):
        return None
    return not bool(al.get("isEnabled"))


def canais_permitidos(camp):
    """Nomes dos canais escolhidos (vazio = aberta a todos ou sem informacao)."""
    al = camp.get("allow") or {}
    return [(c or {}).get("name") or "" for c in (al.get("channels") or []) if c]


def exige_sub(camp):
    """Nenhum drop da campanha se ganha so assistindo (todos pedem sub)."""
    drops = camp.get("timeBasedDrops") or []
    if not drops:
        return False
    return all(int(t.get("requiredSubs") or 0) > 0 for t in drops)


def minutos_de(camp):
    """Menor watch EXIGIDO (>0) entre os drops que NAO pedem sub. 0 se nao ha."""
    tempos = [t.get("requiredMinutesWatched") for t in (camp.get("timeBasedDrops") or [])
              if int(t.get("requiredSubs") or 0) == 0
              and isinstance(t.get("requiredMinutesWatched"), int)
              and t.get("requiredMinutesWatched") > 0]
    return min(tempos) if tempos else 0


def amostra_de_canais(canais, k=8):
    """Metade dos maiores, metade dos menores.

    Campanha de evento (ZEVENT, torneio) so aparece nos canais convidados, que
    sao os grandes. Campanha aberta aparece TAMBEM no canal pequeno que
    ninguem convidou — olhar so o topo confundiria uma com a outra.
    """
    if len(canais) <= k:
        return list(canais)
    ordenados = sorted(canais, key=lambda c: -c[2])
    metade = k // 2
    return ordenados[:metade] + ordenados[-(k - metade):]
