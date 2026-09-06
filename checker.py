#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Twitch Drops Radar - checador.

DE ONDE VEM O DADO (mudou em 06/09/2026)
  So da GQL publica da Twitch, perguntada canal a canal. Nenhum agregador de
  terceiro decide mais o que aparece aqui.

  Motivo: o twitchdrops.app (raspagem de HTML) publicou "Minecraft — Amethyst
  Drone", o radar repassou, o piloto abriu live na Misaune e anunciou 61
  operarios pra 1 pessoa real. Perguntada direto naquele mesmo minuto, a
  Twitch disse o contrario: os 13 canais de Minecraft com DropsEnabled tinham
  todos campanha de badge do proprio canal, e o canal da Misaune — ao vivo na
  categoria — nao tinha campanha nenhuma. Intermediario erra e nao avisa; a
  Twitch, perguntada sobre um canal que esta no ar, nao tem como errar.

COMO A LISTA E MONTADA
  1. Onde procurar: as categorias mais assistidas + as categorias que a Twitch
     mostra com drop ligado agora + as que ja tiveram drop antes
     (data/categorias_vigiadas.json, que o proprio checador vai engordando).
  2. Em cada categoria, quem esta ao vivo COM drop ligado.
  3. De uma amostra desses canais (grandes E pequenos), o que a Twitch responde
     que o espectador ganha ali. Isso e a campanha, com nome, prazo, minutos de
     watch e premios de verdade.
  4. Sobra a peneira, toda por campo da PROPRIA campanha (nada de amostragem):
     `allow`            aberta a todos x lista de canais convidados. Em 06/09 o
                        ALGS do Apex (161 convidados) e o ZEVENT (338) passaram
                        na peneira antiga por aparecerem em varios canais — a
                        lista de permitidos e o que prova, nao a contagem.
     `distributionType` item de jogo (DIRECT_ENTITLEMENT) x badge da Twitch
                        (BADGE). Badge e a fotinha do chat; drop e coisa do
                        jogo. Onimusha Armament, Sorcerer Rogier e Dawnwalker
                        Launch sao BADGE servidas da mesma pasta de imagem dos
                        itens — por isso a imagem nao decide mais.
     `requiredSubs`     drop de sub ("Split 3 - Sub Drop", "ANNIVERSARY PREVIEW
                        SUB") nao se ganha assistindo. ENTRA marcado
                        (requer_sub, subs_necessarios, resgate): pro dono do
                        canal, sub presenteada e dinheiro — o bot decide.

A UNICA COISA QUE NAO VEM DA TWITCH e a aba "Badges chegando" (streamdatabase),
que anuncia badge de evento que AINDA VAI existir. A GQL so sabe do que esta
ativo num canal ao vivo, entao nao ha como tirar isso dela. Essa aba nunca
gerou live: o bot ignora a chave `badges` de proposito.

Regras (pedido do dono):
  - So ABERTO a qualquer streamer. Campanha de canal especifico descartada.
  - jogos-fora.txt manda: jogo listado nao aparece.
  - reward_type: "game" (item de jogo) vs "platform" (badge/emote). Badge da
    Twitch ABERTA a todos entra no feed marcada "platform", e o bot sobe live
    nela tambem (dono, 06/09/2026) — anunciando BADGE no titulo em vez de
    DROPS. `tipo_premio`, `resgate`, `required_minutes` e `subs_necessarios`
    dizem ao bot o que e e como se ganha.
"""
import json
import os
import re
import unicodedata
import datetime
import urllib.request
import urllib.error

import twitch_gql as tw

STREAMDB = "https://www.streamdatabase.com/events"
# lista de jogos que eu nao quero ver, editavel pelo proprio github de
# qualquer PC. Um jogo por linha, "#" e comentario.
AQUI = os.path.dirname(os.path.abspath(__file__))
FORA_ARQ = os.path.join(AQUI, "jogos-fora.txt")
FORA_URL = "https://raw.githubusercontent.com/xguestext/Drops/main/jogos-fora.txt"
VIGIADAS_ARQ = os.path.join(AQUI, "data", "categorias_vigiadas.json")
CONHECIDAS_ARQ = os.path.join(AQUI, "data", "campanhas_conhecidas.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) drops-radar/3.0"}

# Quantas categorias no maximo se olha por rodada. Cada uma custa 1 chamada, e
# as que tem canal com drop custam mais 6. Com 140 a rodada fica em ~2-4 min no
# Actions, que roda de 10 em 10 min (na pratica 40-50).
MAX_CATEGORIAS = 140
# Quantos canais se pergunta por categoria. 6 ja separa campanha aberta (aparece
# em todos) de campanha de um canal so, sem multiplicar o custo.
CANAIS_POR_CATEGORIA = 6
# Nao ha mais "minimo de canais" nem prova por amostragem: aberta ou fechada e
# o `allow` da propria campanha (ver twitch_gql.aberta_a_todos). Uma campanha
# aberta vista num canal so ja vale — e e justamente o drop sem concorrencia.
# Categoria que ficou este tanto de dias sem nenhum drop sai da lista de vigiadas.
DIAS_VIGIANDO = 45
# Por quanto tempo uma campanha ja confirmada continua no feed sem ser vista de
# novo. Existe porque a campanha so aparece se ALGUEM estiver ao vivo com drop
# na categoria: jogo pequeno fica horas sem ninguem transmitindo, e some do
# radar bem na hora em que ele e mais interessante (drop sem concorrencia).
# Nao e chute: a campanha foi vista pela Twitch, com id e prazo dela — o que se
# assume aqui e so que ela nao morreu antes da data que a propria Twitch deu.
HORAS_LEMBRANDO = 24.0


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def now_iso():
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, as_json=True):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if as_json else body


# ---------------- a lista de fora ----------------

def _chave_jogo(t):
    """Minuscula, sem acento e sem pontuacao: assim "Metin 2" e "Metin2"
    viram a mesma coisa, e "black desert" casa dentro de "Black Desert
    Online"."""
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", t)


def carrega_fora():
    """Le o jogos-fora.txt e devolve as chaves ja normalizadas.

    No GitHub Actions o repo acabou de ser clonado, entao o arquivo do disco
    e a verdade. Rodando em casa (alerta_drops.py) o clone pode estar velho,
    entao pega a versao publicada e so cai no disco se faltar rede.
    """
    texto = None
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            texto = fetch(FORA_URL, as_json=False)
        except Exception:
            texto = None
    if texto is None:
        try:
            with open(FORA_ARQ, encoding="utf-8") as f:
                texto = f.read()
        except OSError:
            return []
    fora = []
    for linha in texto.splitlines():
        k = _chave_jogo(linha.split("#", 1)[0])
        if k:
            fora.append(k)
    return fora


def esta_fora(nome, fora):
    k = _chave_jogo(nome)
    return bool(k) and any(f in k for f in fora)


# ---------------- categorias vigiadas (memoria do radar) ----------------

def carrega_vigiadas():
    """{categoria: data ISO do ultimo drop visto ali}.

    Existe porque a Twitch nao deixa paginar a lista de categorias sem o token
    do navegador: sem memoria, o radar so enxergaria as 30 categorias do topo e
    perderia drop de jogo pequeno — que e justamente onde o piloto tem menos
    concorrencia.
    """
    try:
        with open(VIGIADAS_ARQ, encoding="utf-8") as f:
            d = json.load(f)
        return dict(d.get("categorias") or {})
    except Exception:
        return {}


def salva_vigiadas(vigiadas):
    corte = (now_utc() - datetime.timedelta(days=DIAS_VIGIANDO)).strftime("%Y-%m-%d")
    limpa = {k: v for k, v in vigiadas.items() if (v or "")[:10] >= corte}
    os.makedirs(os.path.dirname(VIGIADAS_ARQ), exist_ok=True)
    with open(VIGIADAS_ARQ, "w", encoding="utf-8") as f:
        json.dump({"updated_at": now_iso(), "categorias": limpa}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)
    return limpa


# ---------------- memoria das campanhas ja confirmadas ----------------

def carrega_conhecidas():
    try:
        with open(CONHECIDAS_ARQ, encoding="utf-8") as f:
            return dict((json.load(f).get("campanhas") or {}))
    except Exception:
        return {}


def _velha_demais(reg, agora):
    visto = reg.get("visto_em") or ""
    try:
        quando = datetime.datetime.fromisoformat(visto.replace("Z", "+00:00"))
    except Exception:
        return True
    if quando.tzinfo is None:
        # Data sem fuso (arquivo mexido na mao) passa no parse e estoura na
        # conta abaixo, que compara com `agora`, que TEM fuso. A memoria so e
        # escrita em UTC: le como UTC em vez de derrubar a rodada inteira — e
        # `main()` nao tem try, entao isso matava o commit do Actions e
        # congelava o feed se dizendo fresco.
        quando = quando.replace(tzinfo=datetime.timezone.utc)
    return (agora - quando).total_seconds() > HORAS_LEMBRANDO * 3600


def _ja_acabou(reg, agora_iso):
    fim = reg.get("end_at") or ""
    return bool(fim) and fim <= agora_iso


def _ainda_serve(reg):
    """Entrada da memoria que passaria na peneira de hoje.

    A memoria guarda a campanha inteira, e a peneira mudou em 06/09: o que foi
    gravado como "aberta" pela regra antiga (Apex ALGS, ZEVENT, badges com
    imagem de item) voltaria pro feed por 24h se nao fosse reconferido aqui.
    Entrada sem `tipo_premio` e do formato antigo e cai fora de uma vez.
    """
    return (isinstance(reg, dict) and "tipo_premio" in reg
            and reg.get("availability") == "open")


def lembrar(abertas, agora, agora_iso):
    """Junta o que se viu AGORA com o que ainda vale da rodada passada.

    Devolve (lista pro feed, memoria). Campanha vista agora manda: ela entra
    com os dados frescos e reinicia o relogio da lembranca. Quem grava a
    memoria e `guardar_conhecidas`, depois — e so drop de jogo entra nela.
    """
    conhecidas = carrega_conhecidas()
    vistas_agora = set()
    for c in abertas:
        c["vista_agora"] = True
        c["visto_em"] = agora_iso
        conhecidas[c["id"]] = c
        vistas_agora.add(c["id"])

    lembradas = []
    for cid, reg in list(conhecidas.items()):
        if (_ja_acabou(reg, agora_iso) or _velha_demais(reg, agora)
                or not _ainda_serve(reg)):
            conhecidas.pop(cid, None)
            continue
        if cid in vistas_agora:
            continue
        copia = dict(reg)
        copia["vista_agora"] = False
        lembradas.append(copia)
    return abertas + lembradas, conhecidas


def guardar_conhecidas(campanhas, memoria, agora_iso):
    """Grava a memoria DEPOIS da prova de abertura.

    Antes isto ficava dentro do `lembrar`, e a prova rodava depois: o campo
    `prova` nunca chegava ao disco e toda rodada refazia as ~200 perguntas —
    fora que a campanha lembrada entrava no feed sem nunca ser provada.
    """
    for c in campanhas:
        memoria[c["id"]] = c
    os.makedirs(os.path.dirname(CONHECIDAS_ARQ), exist_ok=True)
    with open(CONHECIDAS_ARQ, "w", encoding="utf-8") as f:
        json.dump({"updated_at": agora_iso, "campanhas": memoria}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)


# ---------------- fonte unica: a GQL da Twitch ----------------

def _janela(c):
    """(inicio, fim) da campanha, em ISO.

    A consulta do player nao devolve `startAt` no nivel da campanha — so dentro
    de cada drop dela. Sem isso o feed sairia com start_at nulo em TUDO, e o bot
    recusaria todas: `campanha_serve` (drops_auto.py) exige hora de inicio pra
    medir a janela de 24h e responde "sem hora de inicio" pra quem nao tem.
    Ou seja: faltar este campo nao daria drop errado, daria drop NENHUM.
    """
    inicios = [t.get("startAt") for t in (c.get("timeBasedDrops") or []) if t.get("startAt")]
    fins = [t.get("endAt") for t in (c.get("timeBasedDrops") or []) if t.get("endAt")]
    inicio = c.get("startAt") or (min(inicios) if inicios else None)
    fim = c.get("endAt") or (max(fins) if fins else None)
    return inicio, fim


def _jogo_da_campanha(c, categoria, capa, slug):
    """Que jogo carimbar: o que a PROPRIA campanha diz; a categoria e o plano B.

    A mesma campanha aparece em canais de categorias diferentes: em 06/09 a
    "First Partners Collection" (evento do Pokemon, jogo "Special Events")
    respondia em Just Chatting E em Pokemon FireRed ao mesmo tempo. Como as
    campanhas sao indexadas so pelo id, ela ficava com o jogo da PRIMEIRA
    categoria varrida — e essa ordem muda a cada rodada, entao o mesmo drop
    saia ora "Just Chatting", ora outro nome. Esse campo e o que o piloto usa
    pra escolher a categoria da live, procurar gameplay e casar com o
    jogos-fora.txt: nome que troca sozinho e nome que o dono nao consegue
    barrar. Capa e slug sao da CATEGORIA — com jogo diferente, mentiriam.
    """
    g = c.get("game")
    nome = ((g or {}).get("name") or "").strip() if isinstance(g, dict) else ""
    if not nome or _chave_jogo(nome) == _chave_jogo(categoria):
        return categoria, capa, slug
    return nome, None, ""


def _campanha_vazia(c, categoria, capa, slug):
    inicio, fim = _janela(c)
    categoria, capa, slug = _jogo_da_campanha(c, categoria, capa, slug)
    aberta = tw.aberta_a_todos(c)
    tipo = tw.tipo_da_campanha(c)
    permitidos = tw.canais_permitidos(c)
    return {
        "id": c.get("id"),
        "name": (c.get("name") or "").strip(),
        "status": "ACTIVE",
        "start_at": inicio,
        "end_at": fim,
        "image": c.get("imageURL") or "",
        "details_url": c.get("detailsURL") or c.get("accountLinkURL") or "",
        "game": categoria,
        "game_slug": slug or _chave_jogo(categoria),
        "game_box": capa or None,
        # "open" SO quando a Twitch diz que nao ha lista de convidados. Sem o
        # campo (`unknown`) nao se publica como aberta: o dono prefere perder um
        # drop a subir live num fechado e gastar credito a toa.
        "availability": "open" if aberta else ("unknown" if aberta is None else "closed"),
        "channels": permitidos[:12],
        "canais_permitidos": len(permitidos),
        "required_minutes": tw.minutos_de(c),
        "requer_sub": tw.exige_sub(c),
        "subs_necessarios": tw.subs_necessarios(c),
        # Em portugues, pro painel e pra torre: "assistir 15 min", "dar 2 subs".
        "resgate": tw.resgate(c),
        "reward_type": "game" if tipo == "game" else "platform",
        "tipo_premio": tipo,
        "rewards": [{"name": n, "image": u, "minutes": m, "type": t, "subs": sb}
                    for n, u, m, t, sb in tw._premios(c)],
        "dono": ((c.get("owner") or {}).get("name") or ""),
        "descricao": (c.get("description") or "").strip()[:200],
        "src": "twitch-gql",
        # Rastro de como se soube disso: em que canais ao vivo ela foi vista.
        "canais_vistos": [],
        "canais_perguntados": 0,
    }


def varrer():
    """Varre a Twitch e devolve o material bruto ja agrupado por campanha."""
    erros = []
    vigiadas = carrega_vigiadas()

    candidatas = []

    def junta(nomes):
        for n in nomes:
            if n and n not in candidatas:
                candidatas.append(n)

    try:
        junta(tw.categorias_quentes())
    except tw.ErroGQL as e:
        erros.append("categorias com drop agora: %s" % e)
    try:
        junta([n for n, _v in tw.top_categorias(30)])
    except tw.ErroGQL as e:
        erros.append("categorias do topo: %s" % e)
    # As vigiadas entram por ultimo e da mais recente pra mais velha: se o teto
    # cortar alguem, corta quem ha mais tempo nao tem drop.
    junta([n for n, _q in sorted(vigiadas.items(), key=lambda kv: kv[1], reverse=True)])
    candidatas = candidatas[:MAX_CATEGORIAS]

    campanhas = {}
    por_cat = {}                 # categoria -> info (serve pra prova de abertura)
    categorias_com_drop = 0
    perguntas = 0
    for nome in candidatas:
        try:
            info = tw.categoria_com_canais(nome)
        except tw.ErroGQL as e:
            erros.append("%s: %s" % (nome, e))
            continue
        if not info or not info["canais"]:
            continue
        por_cat[info["nome"]] = info
        categorias_com_drop += 1
        amostra = tw.amostra_de_canais(info["canais"], CANAIS_POR_CATEGORIA)
        respondidos = 0                  # canais que REALMENTE responderam
        daqui = []                       # campanhas vistas nesta categoria
        for cid, login, _v in amostra:
            try:
                vistas = tw.campanhas_do_canal(cid)
            except tw.ErroGQL as e:
                erros.append("canal %s: %s" % (login, e))
                continue
            perguntas += 1
            respondidos += 1
            for c in vistas:
                if not c.get("id"):
                    continue
                reg = campanhas.get(c["id"])
                if reg is None:
                    reg = _campanha_vazia(c, info["nome"], info["capa"], info["slug"])
                    reg["canais_na_categoria"] = len(info["canais"])
                    campanhas[c["id"]] = reg
                if c["id"] not in daqui:
                    daqui.append(c["id"])
                if login not in reg["canais_vistos"]:
                    reg["canais_vistos"].append(login)
        # Denominador honesto: quantos canais RESPONDERAM, nao quantos estavam
        # na amostra. Canal que levou 429 nao perguntou nada, e categoria de
        # jogo pequeno as vezes so tem UM streamer no ar — guardar o tamanho da
        # amostra fazia "1 de 1 que respondeu" parecer "1 de 6".
        for cid_camp in daqui:
            campanhas[cid_camp]["canais_perguntados"] = max(
                campanhas[cid_camp].get("canais_perguntados") or 0, respondidos)

    return {"campanhas": list(campanhas.values()), "erros": erros,
            "por_cat": por_cat,
            "categorias_olhadas": len(candidatas),
            "categorias_com_drop": categorias_com_drop,
            "canais_perguntados": perguntas, "vigiadas": vigiadas}


def peneirar(campanhas, fora):
    """Separa o que vai pro site do que e descartado — e diz por que.

    Tudo por campo da propria campanha (ver twitch_gql): a Twitch diz quem pode
    (`allow`) e o que e o premio (`distributionType`). Drop de sub NAO e mais
    barrado aqui: entra marcado (requer_sub / subs_necessarios) e o bot decide.
    """
    b = {"abertas": [], "badges_abertas": [], "fechadas": [],
         "de_canal": [], "sem_info": [], "fora_da_lista": []}
    for c in campanhas:
        if esta_fora(c.get("game"), fora):
            b["fora_da_lista"].append(c)
        elif c.get("availability") == "unknown":
            # Sem `allow` na resposta nao da pra provar que e aberta.
            b["sem_info"].append(c)
        elif c.get("availability") != "open":
            # Lista de convidados. Badge de canal (subathon, aniversario) e
            # exatamente isso com um canal so; drop de evento (Apex ALGS,
            # ZEVENT) idem, com centenas. Nenhum dos dois o piloto consegue.
            (b["de_canal"] if c.get("reward_type") != "game" else b["fechadas"]).append(c)
        elif c.get("reward_type") != "game":
            # Badge da Twitch aberta a todos: vale live tambem, anunciada como badge.
            b["badges_abertas"].append(c)
        else:
            b["abertas"].append(c)
    return b


# ---------------- badges chegando (unica coisa que a GQL nao sabe) ----------------

def carrega_badges(agora):
    """Badge de evento que ainda VAI existir (streamdatabase).

    Nao vira drop nem live: o bot ignora esta chave de proposito. Fica porque e
    a unica parte do site que fala do FUTURO — a Twitch so responde sobre o que
    esta ativo num canal ao vivo neste minuto, entao nao ha como tirar dela.
    """
    pagina = fetch(STREAMDB, as_json=False)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', pagina, re.S)
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


# ---------------- feed pronto (alerta_drops.py e drops_tray.py) ----------------

FEED_URL = "https://xguestext.github.io/Drops/data/drops.json"


def coletar(incluir_badges=True):
    """O que o site JA publicou, no formato que o alerta e a bandeja esperam.

    Quem varre a Twitch canal a canal e o `varrer()`, e ele roda no GitHub
    Actions: sao ~310 perguntas por rodada. Refazer isso no PC de casa a cada
    5 minutos seria bater na Twitch pelo IP do dono — o alerta sempre existiu
    justamente pra nao fazer isso. Entao aqui so se le o drops.json publicado:
    o MESMO material do site e do piloto.

    A assinatura e as chaves sao as de antes de propriedade: `alerta_drops.py` e
    `drops_tray.py` (este sobe sozinho no boot do Windows) chamam
    `coletar(incluir_badges=...)` e leem `camps`/`badges`. Quando esta funcao
    virou a varredura, os dois passaram a morrer com TypeError — e o tray, que
    engole excecao, ficaria mudo pra sempre sem ninguem perceber.
    """
    d = fetch(FEED_URL)
    return {
        "camps": d.get("campaigns") or [],
        "badges": (d.get("badges") or []) if incluir_badges else [],
        "fechadas": [],
        "erros": [d["error"]] if d.get("error") else [],
        "source_updated": d.get("source_updated") or d.get("updated_at"),
    }


# ---------------- principal ----------------

def write(result):
    destino = os.path.join(AQUI, "data")
    os.makedirs(destino, exist_ok=True)
    with open(os.path.join(destino, "drops.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("ok=%s campanhas=%d badges=%d" %
          (result["ok"], len(result["campaigns"]), len(result["badges"])))


def main():
    agora = now_utc()
    result = {
        "updated_at": now_iso(), "ok": False, "source": "twitch-gql",
        "source_updated": None, "counts": {}, "campaigns": [], "badges": [],
        "error": None, "warn": None, "raw_hint": None,
    }

    col = varrer()
    fora = carrega_fora()
    pen = peneirar(col["campanhas"], fora)
    publicadas = pen["abertas"] + pen["badges_abertas"]
    vistas_agora = len(publicadas)

    # Rodada ruim NAO apaga a memoria. Se a Twitch nao respondeu, o que se sabia
    # continua valendo pelo prazo dela — o contrario publicaria "nenhum drop no
    # mundo" por causa de um tropeco de rede. Badge aberta entra na memoria
    # tambem: desde 06/09 ela vale live.
    publicadas, memoria = lembrar(publicadas, agora, result["updated_at"])
    guardar_conhecidas(publicadas, memoria, result["updated_at"])
    # A lista de fora pode ter mudado desde a rodada passada: peneira de novo,
    # senao jogo recem-bloqueado voltaria pela memoria.
    publicadas = [c for c in publicadas if not esta_fora(c.get("game"), fora)]

    # Quem acaba primeiro vem primeiro: a urgencia real de quem quer farmar.
    ordem = lambda c: (c.get("end_at") or "9999", c.get("game") or "")
    abertas = sorted([c for c in publicadas if c.get("reward_type") == "game"], key=ordem)
    badges_abertas = sorted([c for c in publicadas if c.get("reward_type") != "game"], key=ordem)

    try:
        result["badges"] = carrega_badges(result["updated_at"])
    except Exception as e:
        col["erros"].append("badges (streamdatabase): %s" % e)

    if abertas or col["canais_perguntados"]:
        # Rodada valida: a Twitch respondeu. Zero campanha aberta e um resultado
        # legitimo, desde que alguem tenha RESPONDIDO sobre campanha — o
        # contador certo e `canais_perguntados`, que so sobe depois da pergunta
        # que PRODUZ campanha responder (a lista de canais e outra query).
        result["ok"] = True
        if col["erros"]:
            result["warn"] = "Tropecos na varredura: " + "; ".join(col["erros"][:4])
    else:
        result["error"] = (
            "A Twitch nao respondeu sobre campanha nesta rodada (%d categorias "
            "com canal no ar, nenhum canal respondeu): %s"
            % (col["categorias_com_drop"], "; ".join(col["erros"][:3]) or "?"))

    # Drop de jogo primeiro; badge da Twitch aberta depois, marcada "platform".
    # O site separa pelo selo; o bot sobe live nos dois, anunciando o que e.
    result["campaigns"] = abertas + badges_abertas
    result["source_updated"] = result["updated_at"]
    result["counts"] = {
        "total": len(result["campaigns"]),
        "upcoming": 0,
        "active": len(result["campaigns"]),
        "game_drops": len(abertas),
        "platform": len(badges_abertas),
        "badges": len(result["badges"]),
        "fechadas_descartadas": len(pen["fechadas"]) + len(pen["de_canal"]),
        "so_canais_escolhidos": len(pen["fechadas"]),
        "badges_de_canal": len(pen["de_canal"]),
        "so_sub": sum(1 for c in result["campaigns"] if c.get("requer_sub")),
        "sem_permissao_info": len(pen["sem_info"]),
        "fora_da_lista": len(pen["fora_da_lista"]),
        "categorias_olhadas": col["categorias_olhadas"],
        "categorias_com_drop": col["categorias_com_drop"],
        "canais_perguntados": col["canais_perguntados"],
        "vistas_agora": vistas_agora,
        "lembradas": max(0, len(abertas) - vistas_agora),
    }

    # Memoria pro proximo ciclo: categoria que entregou drop aberto continua
    # sendo vigiada mesmo quando cair do topo de audiencia.
    vigiadas = col["vigiadas"]
    hoje = now_iso()
    for c in abertas + badges_abertas:
        if c.get("game"):
            vigiadas[c["game"]] = hoje
    salva_vigiadas(vigiadas)

    write(result)


if __name__ == "__main__":
    main()
