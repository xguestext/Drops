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
  4. Sobra a peneira: premio de item de jogo (a Twitch serve a imagem de
     /twitch-quests-assets/REWARD/) e visto em 2+ canais diferentes. Badge de
     canal (aniversario, subathon: imagem de /badges/) fica de fora, que e a
     mesma regra de sempre — "so o que qualquer streamer consegue".

A UNICA COISA QUE NAO VEM DA TWITCH e a aba "Badges chegando" (streamdatabase),
que anuncia badge de evento que AINDA VAI existir. A GQL so sabe do que esta
ativo num canal ao vivo, entao nao ha como tirar isso dela. Essa aba nunca
gerou live: o bot ignora a chave `badges` de proposito.

Regras (pedido do dono):
  - So ABERTO a qualquer streamer. Campanha de canal especifico descartada.
  - jogos-fora.txt manda: jogo listado nao aparece.
  - reward_type: "game" (item de jogo) vs "platform" (badge/emote).
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
CANAIS_ARQ = os.path.join(AQUI, "data", "canais_por_campanha.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) drops-radar/3.0"}

# Quantas categorias no maximo se olha por rodada. Cada uma custa 1 chamada, e
# as que tem canal com drop custam mais 6. Com 140 a rodada fica em ~2-4 min no
# Actions, que roda de 10 em 10 min (na pratica 40-50).
MAX_CATEGORIAS = 140
# Quantos canais se pergunta por categoria. 6 ja separa campanha aberta (aparece
# em todos) de campanha de um canal so, sem multiplicar o custo.
CANAIS_POR_CATEGORIA = 6
# Campanha vista em menos canais que isto nao e "aberta a qualquer streamer".
MINIMO_CANAIS = 2
# A PROVA DA ABERTURA: quantos canais COMUNS (afiliados sem a tag de drops) se
# pergunta, e quantos precisam ter respondido pra valer uma condenacao.
# Medido em 06/09: o "Split 3 - Sub Drop" do LoL nao aparecia em 8 canais comuns
# (e drop de SUB dos canais oficiais) e o "NBA 2K27 Season 1" em nenhum dos 6
# afiliados — os dois estavam no feed como se qualquer um pudesse fazer.
CANAIS_PROVA = 6
MINIMO_PROVA = 3
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


def provar_abertura(campanhas, por_cat, memoria):
    """Um canal COMUM da categoria tambem ganha? Devolve (aprovadas, reprovadas).

    A peneira de cima ja separa item de jogo de badge de canal, mas ela nao
    distingue "drop do jogo" de "drop do EVENTO": a campanha do ZEVENT, o sub
    drop do LoL e o pacote da NBA 2K27 aparecem em varios canais — so que em
    canais CONVIDADOS. Como o piloto so sobe live em canal dele, campanha assim
    e live paga sem premio nenhum.

    A pergunta que resolve: um afiliado qualquer da categoria, que nem marcou a
    tag de drops, ganha isso? Se ganha, qualquer um ganha. Testado em 06/09:
    "Conquest Mode Drops" 4 de 4 afiliados ganham; "NBA 2K27 Season 1", 0 de 6.

    Falha ABERTO de proposito: so reprova com pelo menos MINIMO_PROVA canais
    respondendo. Categoria sem afiliado comum no ar (ou so com parceiro) fica
    como estava — barrar drop de verdade custa mais caro que uma live a toa, e o
    piloto ainda tem a conferencia dele antes de gastar operario.
    """
    aprovadas, reprovadas = [], []
    for c in campanhas:
        lembrado = (memoria.get(c["id"]) or {}).get("prova")
        if lembrado in ("aberta", "so convidados"):
            c["prova"] = lembrado
            (aprovadas if lembrado == "aberta" else reprovadas).append(c)
            continue
        info = por_cat.get(c["game"])
        try:
            lista = tw.canais_comuns(info["nome"] if info else c["game"])
        except tw.ErroGQL:
            c["prova"] = "nao deu pra conferir"
            aprovadas.append(c)
            continue
        # O gemeo das contas do dono: afiliado, nao parceiro, sem a tag de drops.
        iguais = [x for x in lista if x["afiliado"] and not x["parceiro"] and not x["marcado"]]
        if len(iguais) < MINIMO_PROVA:
            # Categoria de gente grande (LoL, e-sport) as vezes nao tem afiliado
            # comum no ar. Ai vale qualquer canal sem a tag: se NEM o parceiro
            # ganha, ninguem de fora ganha.
            iguais += [x for x in lista
                       if not x["marcado"] and x not in iguais]
        ganham = perguntados = 0
        for x in iguais[:CANAIS_PROVA]:
            try:
                vistas = tw.campanhas_do_canal(x["id"])
            except tw.ErroGQL:
                continue
            perguntados += 1
            if any(v.get("id") == c["id"] for v in vistas):
                ganham += 1
                break                      # um basta: ja provou que e aberta
        if ganham:
            c["prova"] = "aberta"
            aprovadas.append(c)
        elif perguntados >= MINIMO_PROVA:
            c["prova"] = "so convidados"
            reprovadas.append(c)
        else:
            c["prova"] = "nao deu pra conferir"
            aprovadas.append(c)
    return aprovadas, reprovadas


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


def lembrar(abertas, agora, agora_iso):
    """Junta o que se viu AGORA com o que ainda vale da rodada passada.

    Devolve (lista pro feed, memoria nova). Campanha vista agora manda: ela
    entra com os dados frescos e reinicia o relogio da lembranca.
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
        if _ja_acabou(reg, agora_iso) or _velha_demais(reg, agora):
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


def juntar_canais(campanhas, agora, agora_iso):
    """Soma os canais desta rodada aos que ja se viu da MESMA campanha antes.

    MINIMO_CANAIS pede 2 canais distintos, e ate aqui os dois tinham que estar
    ao vivo NO MESMO MINUTO. Jogo pequeno quase nunca tem dois ao mesmo tempo,
    e campanha barrada nao deixava rastro nenhum: cada rodada recomecava do
    zero. Medido em 06/09: "B&S NEO Reignited Drops" (Blade & Soul NEO, item de
    jogo, 120 min de watch, prazo da propria Twitch) teve 1 canal as 08:19 e 1
    canal as 08:34 — e nunca entrou no feed. Era justo o caso que mais interessa
    pro dono: drop de verdade sem concorrencia.

    A prova nao fica mais fraca por ser somada com o tempo: e o mesmo id de
    campanha respondido por dois canais DIFERENTES, que e exatamente o que
    MINIMO_CANAIS mede. Campanha de canal (subathon, aniversario) segue barrada
    pra sempre — ela so existe naquele canal, por mais rodadas que passem.

    Vale a mesma regua do resto da memoria: some quando a campanha acaba (pelo
    end_at da propria Twitch) ou quando fica HORAS_LEMBRANDO sem ser vista.
    """
    try:
        with open(CANAIS_ARQ, encoding="utf-8") as f:
            antes = dict((json.load(f).get("campanhas") or {}))
    except Exception:
        antes = {}

    novo = {}
    for c in campanhas:
        reg = antes.get(c["id"]) or {}
        if reg and not (_ja_acabou(reg, agora_iso) or _velha_demais(reg, agora)):
            for login in reg.get("canais_vistos") or []:
                if login not in c["canais_vistos"]:
                    c["canais_vistos"].append(login)
        # So campanha de item precisa disto: badge e barrada pelo tipo do
        # premio, nao pela contagem de canais.
        if c.get("reward_type") == "game":
            novo[c["id"]] = {"canais_vistos": list(c["canais_vistos"]),
                             "end_at": c.get("end_at"), "visto_em": agora_iso}

    # Quem nao apareceu nesta rodada fica guardado ate vencer: o unico canal
    # daquele jogo pode estar offline agora e voltar na proxima.
    for cid, reg in antes.items():
        if cid in novo:
            continue
        if _ja_acabou(reg, agora_iso) or _velha_demais(reg, agora):
            continue
        novo[cid] = reg

    os.makedirs(os.path.dirname(CANAIS_ARQ), exist_ok=True)
    with open(CANAIS_ARQ, "w", encoding="utf-8") as f:
        json.dump({"updated_at": agora_iso, "campanhas": novo}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)
    return campanhas


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
    return {
        "id": c.get("id"),
        "name": (c.get("name") or "").strip(),
        "status": "ACTIVE",
        "start_at": inicio,
        "end_at": fim,
        "image": c.get("imageURL") or "",
        "details_url": c.get("detailsURL") or "",
        "game": categoria,
        "game_slug": slug or _chave_jogo(categoria),
        "game_box": capa or None,
        "availability": "open",
        "channels": [],
        "required_minutes": tw.minutos_de(c),
        "reward_type": "game" if tw.tipo_da_campanha(c) == "game" else "platform",
        "rewards": [{"name": n, "image": u, "minutes": m}
                    for n, u, m in tw._premios(c)],
        "src": "twitch-gql",
        # Rastro de como se soube disso. Se um dia o dono desconfiar de uma
        # campanha, esta e a lista de canais em que ela foi vista ao vivo.
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
                    # Quantos canais existiam pra perguntar, e se a campanha e
                    # do jogo DA CATEGORIA. Os dois so servem pro jogo pequeno
                    # (`_tudo_que_dava_pra_ver`).
                    reg["canais_na_categoria"] = len(info["canais"])
                    reg["campanha_do_jogo"] = bool(info.get("id")) and (
                        (c.get("game") or {}).get("id") == info["id"])
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


def _tudo_que_dava_pra_ver(c):
    """A campanha apareceu em poucos canais porque poucos canais existiam.

    A Twitch so casa campanha com canal AO VIVO, entao categoria pequena as
    vezes tem UM canal com drop ligado no mundo inteiro — e ai "2 canais" e uma
    prova que ninguem consegue dar. Medido em 06/09: o drop do Blade & Soul NEO
    (item, 120 min de watch) barrado porque a categoria tinha 1 canal no ar.

    So passa com as DUAS travas juntas, senao volta a entrar lixo:
      - a campanha e do jogo DA CATEGORIA (a Twitch responde o jogo dentro da
        campanha). Campanha de canal chega com outro jogo — o "Ironmouse
        Subathon 2026" vem como "Special Events" dentro de Kingdom Hearts — e
        continua barrada.
      - nao havia dois canais pra perguntar. Se havia e so um entregou, e
        campanha de convidado (evento tipo ZEVENT) e continua barrada.
    """
    return (bool(c.get("campanha_do_jogo"))
            and int(c.get("canais_na_categoria") or 0) <= 1
            and int(c.get("canais_perguntados") or 0) <= 1
            and len(c.get("canais_vistos") or []) >= 1)


def peneirar(campanhas, fora):
    """Separa o que vai pro site do que e descartado, e diz por que."""
    abertas, de_canal, barradas, fora_da_lista = [], [], [], []
    for c in campanhas:
        if esta_fora(c["game"], fora):
            fora_da_lista.append(c)
            continue
        if c["reward_type"] != "game":
            # Badge/emote de canal: e a maioria esmagadora (84 de 97 numa
            # medicao de 06/09) e nunca foi coisa que o piloto persegue.
            de_canal.append(c)
            continue
        if len(c["canais_vistos"]) < MINIMO_CANAIS and not _tudo_que_dava_pra_ver(c):
            # Item de jogo que so UM canal entrega, existindo outros pra
            # perguntar: campanha de parceria com aquele streamer, nao vale pra
            # quem abrir live agora.
            barradas.append(c)
            continue
        abertas.append(c)
    return abertas, de_canal, barradas, fora_da_lista


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
    # Antes de peneirar: soma os canais que ja se viu desta campanha em rodadas
    # anteriores. Sem isso, drop de jogo pequeno (1 canal por vez) nunca junta
    # os 2 canais que a peneira pede.
    campanhas = juntar_canais(col["campanhas"], agora, result["updated_at"])
    abertas, de_canal, barradas, fora_da_lista = peneirar(campanhas, fora)
    vistas_agora = len(abertas)

    # Rodada ruim NAO apaga a memoria. Se a Twitch nao respondeu, o que se sabia
    # continua valendo pelo prazo dela — o contrario publicaria "nenhum drop no
    # mundo" por causa de um tropeco de rede.
    abertas, memoria = lembrar(abertas, agora, result["updated_at"])
    # A PROVA FINAL, depois de juntar com as lembradas: campanha de EVENTO
    # (canais convidados) passa na peneira de cima, porque aparece mesmo em
    # varios canais. Aqui se pergunta a um canal comum da categoria — se nem
    # ele ganha, nao e drop pra qualquer um. Campanha ja provada antes usa o
    # que ficou guardado, entao isso nao custa uma rodada inteira de perguntas.
    abertas, so_convidados = provar_abertura(abertas, col["por_cat"], memoria)
    barradas += so_convidados
    vistas_agora = min(vistas_agora, len(abertas))
    guardar_conhecidas(abertas + so_convidados, memoria, result["updated_at"])
    # A lista de fora pode ter mudado desde a rodada passada: peneira de novo,
    # senao jogo recem-bloqueado voltaria pela memoria.
    abertas = [c for c in abertas if not esta_fora(c.get("game"), fora)]

    # UPCOMING no topo continuava sendo a ordem do site; sem fonte de campanha
    # futura, a ordem passa a ser quem acaba primeiro (a urgencia real de quem
    # quer farmar).
    abertas.sort(key=lambda c: (c.get("end_at") or "9999", c.get("game") or ""))

    try:
        result["badges"] = carrega_badges(result["updated_at"])
    except Exception as e:
        col["erros"].append("badges (streamdatabase): %s" % e)

    if abertas or col["canais_perguntados"]:
        # Rodada valida: a Twitch respondeu. Zero campanha aberta e um resultado
        # legitimo (ja aconteceu de nao haver drop bom no ar), desde que alguem
        # tenha RESPONDIDO sobre campanha.
        #
        # O contador tem que ser esse e nao `categorias_com_drop`: aquele conta
        # so a query CRUA (a lista de canais), e a campanha vem da persisted
        # query, que pode morrer sozinha (hash rotacionado, integrity passando a
        # ser exigido nela). Com o contador errado a rodada saia "ok" mesmo com
        # as ~300 perguntas de campanha falhando — e `baixar_feed` (no bot) so
        # olha o `ok`: passadas as 24h de memoria o feed viraria "nenhum drop no
        # mundo", calado, pra sempre.
        result["ok"] = True
        if col["erros"]:
            result["warn"] = "Tropecos na varredura: " + "; ".join(col["erros"][:4])
    else:
        result["error"] = (
            "A Twitch nao respondeu sobre campanha nesta rodada (%d categorias "
            "com canal no ar, nenhum canal respondeu): %s"
            % (col["categorias_com_drop"], "; ".join(col["erros"][:3]) or "?"))

    result["campaigns"] = abertas
    result["source_updated"] = result["updated_at"]
    result["counts"] = {
        "total": len(abertas),
        "upcoming": 0,
        "active": len(abertas),
        "game_drops": len(abertas),
        "platform": 0,
        "badges": len(result["badges"]),
        "fechadas_descartadas": len(de_canal) + len(barradas),
        "fora_da_lista": len(fora_da_lista),
        "categorias_olhadas": col["categorias_olhadas"],
        "categorias_com_drop": col["categorias_com_drop"],
        "canais_perguntados": col["canais_perguntados"],
        "vistas_agora": vistas_agora,
        "lembradas": len(abertas) - vistas_agora,
    }

    # Memoria pro proximo ciclo: categoria que entregou drop aberto continua
    # sendo vigiada mesmo quando cair do topo de audiencia.
    vigiadas = col["vigiadas"]
    hoje = now_iso()
    for c in abertas:
        if c.get("game"):
            vigiadas[c["game"]] = hoje
    salva_vigiadas(vigiadas)

    write(result)


if __name__ == "__main__":
    main()
