#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drops Radar - widget de desktop + bandeja.

- BOLINHA sempre por cima de tudo: presentinho + BADGE com o numero de drops/badges
  que voce AINDA NAO VIU (abriu o painel = zera, igual notificacao de mensagem).
  * CLIQUE (esquerdo)      -> abre o painel com os drops e badges
  * BOTAO DIREITO arrasta  -> move a bolinha (posicao fica salva)
  * BOTAO DIREITO (soltar sem arrastar) -> menu (atualizar / site / esconder / sair)
- PAINEL: janela local bonita (painel.html renderizado pelo Edge em modo app, com os
  dados que o vigia escreve no disco — sem depender do site).
- NOTIFICACOES (cards iguais ao site) empilham em cima da bolinha.
- Liga no boot, morre no desligar ou no Sair.

Uso: pythonw drops_tray.py          (normal)
     python  drops_tray.py --demo   (bolinha + painel + 2 notificacoes de exemplo)
"""
import io
import os
import re
import sys
import json
import queue
import ctypes
import socket
import pathlib
import threading
import subprocess
import datetime
import urllib.request
import tkinter as tk

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import checker            # noqa: E402
import alerta_drops as al  # noqa: E402

from PIL import Image, ImageDraw, ImageTk, ImageFont  # noqa: E402
import pystray             # noqa: E402

SITE = "https://xguestext.github.io/Drops/"
PYW = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python314\pythonw.exe")
if not os.path.exists(PYW):
    PYW = "pythonw"

BG, CARD, CARD2, LINHA = "#0d0d10", "#17171b", "#1e1e24", "#2a2a32"
TXT, DIM, FAINT = "#efeff1", "#b0b0bb", "#787885"
AZUL, VERDE, AMBAR, ROXO, ROXO_LT = "#3ea6ff", "#2ec16a", "#f0a83c", "#9147ff", "#c9a6ff"
PILL_AZUL, PILL_VERDE, PILL_ROXO, PILL_AMBAR, PILL_CINZA = "#1c2b3b", "#1a2d25", "#281e3b", "#352b20", "#232329"
CHAVE_TRANSP = "#010101"

CACHE = {"ups": [], "atv": [], "badges": [], "quando": None}
THUMBS = {}
VISTO = {"panel": set()}
WIDGET = {"bolinha": None, "icon": None}
PAINEL_PROC = {"p": None}

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


def fonte(px, peso="regular"):
    nomes = {"regular": ["segoeui.ttf"], "bold": ["segoeuib.ttf", "seguisb.ttf", "segoeui.ttf"],
             "semi": ["seguisb.ttf", "segoeuib.ttf", "segoeui.ttf"]}
    for n in nomes.get(peso, ["segoeui.ttf"]):
        try:
            return ImageFont.truetype(n, px)
        except Exception:
            continue
    return ImageFont.load_default()


def rel_curto(iso):
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        s = (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if s <= 0:
            return "agora"
        if s < 3600:
            return "%d min" % round(s / 60)
        if s < 86400:
            return "%d h" % round(s / 3600)
        d = round(s / 86400)
        return "%d dia%s" % (d, "s" if d > 1 else "")
    except Exception:
        return "?"


def data_curta(iso):
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m")
    except Exception:
        return "?"


def baixa_imagem(url):
    if not url:
        return None
    if url in THUMBS:
        return THUMBS[url]
    u = url.replace("{width}", "112").replace("{height}", "152")
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "drops-radar-tray/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            img = Image.open(io.BytesIO(r.read())).convert("RGB")
        img.thumbnail((160, 220))
        THUMBS[url] = img
        return img
    except Exception:
        return None


def cobre(img, alvo):
    if img is None:
        return None
    r_alvo = alvo[0] / alvo[1]
    r_img = img.width / img.height
    if r_img > r_alvo:
        w = int(img.height * r_alvo)
        x = (img.width - w) // 2
        img = img.crop((x, 0, x + w, img.height))
    else:
        h = int(img.width / r_alvo)
        y = (img.height - h) // 2
        img = img.crop((0, y, img.width, y + h))
    return img.resize(alvo, Image.LANCZOS)


def arredonda(img, raio):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], raio, fill=255)
    out = img.convert("RGBA")
    out.putalpha(m)
    return out


def placeholder(letra, alvo, cor=ROXO_LT):
    img = Image.new("RGB", alvo, CARD2)
    d = ImageDraw.Draw(img)
    f = fonte(int(alvo[1] * 0.42), "bold")
    d.text((alvo[0] / 2, alvo[1] / 2), (letra or "?")[:1].upper(), fill=cor, font=f, anchor="mm")
    return img


def _corta(d, txt, f, maxw):
    if d.textlength(txt, font=f) <= maxw:
        return txt
    while txt and d.textlength(txt + "…", font=f) > maxw:
        txt = txt[:-1]
    return txt + "…"


def desenha_presente(d, x, y, t, cor=ROXO, furo=CARD):
    d.rounded_rectangle([x + t * .08, y + t * .30, x + t * .92, y + t * .92], t * .14, fill=cor)
    d.rectangle([x + t * .44, y + t * .30, x + t * .56, y + t * .92], fill=furo)
    d.rectangle([x + t * .08, y + t * .48, x + t * .92, y + t * .57], fill=furo)
    d.rounded_rectangle([x + t * .14, y + t * .10, x + t * .46, y + t * .32], t * .10, outline=cor, width=max(2, int(t * .08)))
    d.rounded_rectangle([x + t * .54, y + t * .10, x + t * .86, y + t * .32], t * .10, outline=cor, width=max(2, int(t * .08)))


# ================= notificacao (card igual ao site) =================

def renderiza_card(dado):
    S = 3
    W = 420 * S
    pad = 16 * S
    stripe = dado.get("cor", AZUL)

    f_eyebrow = fonte(11 * S, "bold")
    f_nome = fonte(15 * S, "semi")
    f_pill = fonte(10 * S, "semi")
    f_tempo = fonte(11 * S)
    f_tempo_b = fonte(11 * S, "bold")
    f_head = fonte(9 * S, "bold")
    f_rw = fonte(10 * S)
    f_min = fonte(10 * S, "bold")

    box_w, box_h = 56 * S, 76 * S
    rewards = dado.get("rewards") or []
    n_rw = min(len(rewards), 2)
    extra = len(rewards) - n_rw
    tem_nota = bool(dado.get("nota"))

    y_top = pad + max(box_h, 68 * S)
    y_pills = y_top + 10 * S
    y_tempo = y_pills + 24 * S + 10 * S
    y_head = y_tempo + 18 * S + 12 * S
    y_rw = y_head + (16 * S if (rewards or tem_nota) else 0)
    H = y_rw + n_rw * (34 * S + 6 * S) + (16 * S if extra > 0 else 0) \
        + (20 * S if tem_nota else 0) + pad
    if not rewards and not tem_nota:
        H = y_tempo + 18 * S + pad

    base = Image.new("RGB", (W, H), CHAVE_TRANSP)
    d = ImageDraw.Draw(base)
    r = 14 * S
    d.rounded_rectangle([0, 0, W - 1, H - 1], r, fill=stripe)
    d.rounded_rectangle([3 * S, 0, W - 1, H - 1], r, fill=CARD, outline=LINHA, width=S)

    box = cobre(dado.get("box"), (box_w, box_h)) or placeholder(dado.get("titulo"), (box_w, box_h))
    box = arredonda(box, 8 * S)
    base.paste(box, (pad + 2 * S, pad), box)

    tx = pad + 2 * S + box_w + 12 * S
    maxw = W - tx - pad
    d.text((tx, pad + 2 * S), _corta(d, (dado.get("eyebrow") or "").upper(), f_eyebrow, maxw),
           fill=dado.get("cor_eyebrow", ROXO_LT), font=f_eyebrow)
    d.text((tx, pad + 20 * S), _corta(d, dado.get("titulo") or "", f_nome, maxw), fill=TXT, font=f_nome)

    x = pad + 2 * S
    for txt_p, cor_txt, cor_bg in dado.get("pills") or []:
        wt = d.textlength(txt_p, font=f_pill)
        wp = int(wt + 30 * S)
        d.rounded_rectangle([x, y_pills, x + wp, y_pills + 22 * S], 11 * S, fill=cor_bg)
        d.ellipse([x + 10 * S, y_pills + 8 * S, x + 16 * S, y_pills + 14 * S], fill=cor_txt)
        d.text((x + 21 * S, y_pills + 4 * S), txt_p, fill=cor_txt, font=f_pill)
        x += wp + 7 * S

    x = pad + 2 * S
    for seg, cor_s, b in dado.get("tempo") or []:
        f = f_tempo_b if b else f_tempo
        d.text((x, y_tempo), seg, fill=cor_s, font=f)
        x += d.textlength(seg, font=f)

    if rewards:
        d.text((pad + 2 * S, y_head), (dado.get("head") or "RECOMPENSAS"), fill=FAINT, font=f_head)
        y = y_rw
        for nome_r, min_r, img_r in rewards[:n_rw]:
            d.rounded_rectangle([pad + 2 * S, y, W - pad, y + 34 * S], 8 * S,
                                fill=CARD2, outline=LINHA, width=S)
            xi = pad + 8 * S
            th = cobre(img_r, (24 * S, 24 * S)) if img_r else None
            if th is not None:
                th = arredonda(th, 5 * S)
                base.paste(th, (int(xi), int(y + 5 * S)), th)
            else:
                d.ellipse([xi + 8 * S, y + 14 * S, xi + 14 * S, y + 20 * S], fill=ROXO)
            min_txt = ("%d min" % min_r) if min_r else ""
            wmin = d.textlength(min_txt, font=f_min) if min_txt else 0
            d.text((xi + 32 * S, y + 9 * S),
                   _corta(d, nome_r or "", f_rw, W - pad - xi - 40 * S - wmin - 12 * S),
                   fill=TXT, font=f_rw)
            if min_txt:
                d.text((W - pad - 10 * S - wmin, y + 9 * S), min_txt, fill=AMBAR, font=f_min)
            y += 40 * S
        if extra > 0:
            d.text((pad + 2 * S, y), "+%d recompensa%s" % (extra, "s" if extra > 1 else ""),
                   fill=FAINT, font=f_rw)
    elif tem_nota:
        d.text((pad + 2 * S, y_head), _corta(d, dado["nota"], f_rw, W - 2 * pad), fill=DIM, font=f_rw)

    return base.resize((W // S, H // S), Image.LANCZOS)


class Notificacao(tk.Toplevel):
    ABERTAS = []

    def __init__(self, root, pil_card, segundos=12):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=CHAVE_TRANSP)
        try:
            self.attributes("-transparentcolor", CHAVE_TRANSP)
        except tk.TclError:
            pass
        self.restante = int(segundos * 10)
        self.pausado = False

        self._img = ImageTk.PhotoImage(pil_card)
        lbl = tk.Label(self, image=self._img, bg=CHAVE_TRANSP, bd=0)
        lbl.pack()
        lbl.bind("<Button-1>", lambda e: self.fechar())
        lbl.bind("<Enter>", lambda e: setattr(self, "pausado", True))
        lbl.bind("<Leave>", lambda e: setattr(self, "pausado", False))

        W, H = pil_card.width, pil_card.height
        self._h = H
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        ocupado = sum(n._h + 10 for n in Notificacao.ABERTAS if n.winfo_exists())

        b = WIDGET.get("bolinha")
        try:
            visivel = b and b.winfo_exists() and b.state() != "withdrawn"
        except tk.TclError:
            visivel = False
        if visivel:
            bx, by = b.winfo_rootx(), b.winfo_rooty()
            x = max(8, min(bx + b.winfo_width() - W, sw - W - 8))
            y = max(8, by - 10 - H - ocupado)
        else:
            x, y = sw - W - 16, sh - 58 - H - ocupado
        self.geometry("%dx%d+%d+%d" % (W, H, x, y))
        Notificacao.ABERTAS.append(self)

        self.attributes("-alpha", 0.0)
        self._fade(0.0, +0.14)
        self.after(100, self._tic)

    def _fade(self, a, passo):
        a = max(0.0, min(1.0, a + passo))
        try:
            self.attributes("-alpha", a)
        except tk.TclError:
            return
        if 0.0 < a < 1.0:
            self.after(20, self._fade, a, passo)
        elif a <= 0.0:
            self._some()

    def _tic(self):
        if not self.winfo_exists():
            return
        if not self.pausado:
            self.restante -= 1
            if self.restante <= 0:
                self._fade(1.0, -0.14)
                return
        self.after(100, self._tic)

    def fechar(self):
        self._fade(1.0, -0.3)

    def _some(self):
        try:
            Notificacao.ABERTAS.remove(self)
        except ValueError:
            pass
        self.destroy()


def monta_drop(c, comecou=False):
    box = baixa_imagem(c.get("game_box") or c.get("image"))
    pill_tipo = ("Item de jogo", ROXO_LT, PILL_ROXO) if c.get("reward_type") == "game" \
        else ("Badge / plataforma", FAINT, PILL_CINZA)
    if comecou:
        pills = [("Ativo", VERDE, PILL_VERDE), pill_tipo]
        tempo = [("termina em ", DIM, False), (rel_curto(c.get("end_at")), TXT, True),
                 (" · até %s" % data_curta(c.get("end_at")), DIM, False)]
        cor = VERDE
    else:
        pills = [("Em breve", AZUL, PILL_AZUL), pill_tipo]
        tempo = [("começa em ", DIM, False), (rel_curto(c.get("start_at")), TXT, True),
                 (" · %s" % data_curta(c.get("start_at")), DIM, False)]
        if c.get("end_at"):
            tempo.append((" → até %s" % data_curta(c.get("end_at")), DIM, False))
        cor = AZUL
    rewards = [(r.get("name"), r.get("minutes"), baixa_imagem(r.get("image")))
               for r in (c.get("rewards") or [])[:3]]
    head = "RECOMPENSAS"
    if c.get("required_minutes"):
        head += " · ATÉ %d MIN ASSISTINDO" % c["required_minutes"]
    return dict(cor=cor, eyebrow=c.get("game"), cor_eyebrow=ROXO_LT,
                titulo=c.get("name") or c.get("game"), pills=pills, tempo=tempo,
                head=head, rewards=rewards, box=box)


def monta_badge(b):
    box = baixa_imagem((b.get("images") or [None])[0])
    if box is not None:
        q = Image.new("RGB", (56, 76), CARD2)
        q.paste(cobre(box, (48, 48)), (4, 14))
        box = q
    tempo = [("começa em ", DIM, False), (rel_curto(b.get("start_at")), TXT, True),
             (" · %s" % data_curta(b.get("start_at")), DIM, False)]
    return dict(cor=AMBAR, eyebrow="Badge da Twitch", cor_eyebrow=AMBAR,
                titulo=b.get("title"), tempo=tempo,
                pills=[("Em breve", AZUL, PILL_AZUL), ("Badge", AMBAR, PILL_AMBAR)],
                rewards=[], nota=(b.get("note") or "Badge global de evento da Twitch")[:70],
                box=box)


def chave_badge(b):
    return re.sub(r"[^a-z0-9]", "", (b.get("title") or "").lower()) + "|" + (b.get("start_at") or "")[:10]


# ================= painel (Edge modo app, local) =================

def acha_navegador():
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    lad = os.environ.get("LOCALAPPDATA", "")
    for c in [os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
              os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
              os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
              os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
              os.path.join(lad, r"Google\Chrome\Application\chrome.exe")]:
        if os.path.exists(c):
            return c
    return None


def abrir_painel():
    """Abre o painel local (e marca tudo como visto -> badge da bolinha zera)."""
    b = WIDGET.get("bolinha")
    chaves = {al.chave(c) for c in CACHE["ups"]} | {chave_badge(x) for x in CACHE["badges"]}
    VISTO["panel"] |= chaves
    if b and b.winfo_exists():
        b.desenha(0)

    p = PAINEL_PROC.get("p")
    if p and p.poll() is None:
        return
    url = pathlib.Path(os.path.join(AQUI, "painel.html")).as_uri()
    nav = acha_navegador()
    if not nav:
        import webbrowser
        webbrowser.open(url)
        return
    W, Hh = 560, 780
    sw = b.winfo_screenwidth() if b else 1920
    sh = b.winfo_screenheight() if b else 1080
    if b and b.winfo_exists():
        bx, by = b.winfo_rootx(), b.winfo_rooty()
        x = max(8, min(bx + b.winfo_width() - W, sw - W - 8))
        y = by - Hh - 12
        if y < 8:
            y = max(8, min(by + b.winfo_height() + 12, sh - Hh - 8))
    else:
        x, y = sw - W - 40, max(8, sh - Hh - 80)
    perfil = os.path.join(os.environ.get("LOCALAPPDATA", AQUI), "DropsRadarPainel")
    PAINEL_PROC["p"] = subprocess.Popen(
        [nav, "--app=" + url, "--window-size=%d,%d" % (W, Hh),
         "--window-position=%d,%d" % (x, y), "--user-data-dir=" + perfil,
         "--no-first-run", "--no-default-browser-check"])


def escreve_dados_painel():
    dados = {"atualizado": CACHE.get("quando"),
             "ups": CACHE["ups"], "atv": CACHE["atv"], "badges": CACHE["badges"]}
    tmp = os.path.join(AQUI, "painel_dados.js.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.DADOS = ")
        json.dump(dados, f, ensure_ascii=False)
        f.write(";")
    os.replace(tmp, os.path.join(AQUI, "painel_dados.js"))


# ================= bolinha =================

class Bolinha(tk.Toplevel):
    def __init__(self, root, ao_clicar, menu_acoes):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=CHAVE_TRANSP)
        try:
            self.attributes("-transparentcolor", CHAVE_TRANSP)
        except tk.TclError:
            pass
        self.ao_clicar = ao_clicar
        self._drag = None
        self._moveu = False

        self.lbl = tk.Label(self, bg=CHAVE_TRANSP, bd=0, cursor="hand2")
        self.lbl.pack()
        self.lbl.bind("<ButtonRelease-1>", lambda e: self.ao_clicar())
        self.lbl.bind("<ButtonPress-3>", self._press)
        self.lbl.bind("<B3-Motion>", self._move)
        self.lbl.bind("<ButtonRelease-3>", self._solta)
        self._menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TXT,
                             activebackground=ROXO, activeforeground="#fff", bd=0)
        for nome, fn in menu_acoes:
            self._menu.add_command(label=nome, command=fn)

        st = al.carrega_estado()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = (st.get("widget_pos") or [sw - 110, sh - 170])
        x = max(0, min(int(x), sw - 70))
        y = max(0, min(int(y), sh - 70))
        self.desenha(0)
        self.geometry("+%d+%d" % (x, y))

    def desenha(self, n_novos):
        S = 4
        W, H = 60 * S, 58 * S
        img = Image.new("RGB", (W, H), CHAVE_TRANSP)
        d = ImageDraw.Draw(img)
        # corpo
        d.rounded_rectangle([2 * S, 10 * S, 50 * S, 58 * S - 2 * S], 15 * S,
                            fill=CARD, outline=LINHA, width=S)
        desenha_presente(d, 11 * S, 18 * S, 30 * S)
        # badge de nao-vistos (some quando 0)
        if n_novos > 0:
            txt = "9+" if n_novos > 9 else str(n_novos)
            f = fonte(11 * S, "bold")
            r = 11 * S
            cx, cy = 46 * S, 12 * S
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AZUL, outline=CARD, width=2 * S)
            d.text((cx, cy - S), txt, fill="#08131d", font=f, anchor="mm")
        self._pil = img.resize((W // S, H // S), Image.LANCZOS)
        self._img = ImageTk.PhotoImage(self._pil)
        self.lbl.configure(image=self._img)

    def _press(self, e):
        self._drag = (e.x_root, e.y_root, self.winfo_x(), self.winfo_y())
        self._moveu = False

    def _move(self, e):
        if not self._drag:
            return
        dx, dy = e.x_root - self._drag[0], e.y_root - self._drag[1]
        if abs(dx) + abs(dy) > 6:
            self._moveu = True
        self.geometry("+%d+%d" % (self._drag[2] + dx, self._drag[3] + dy))

    def _solta(self, e):
        if self._moveu:
            st = al.carrega_estado()
            st["widget_pos"] = [self.winfo_x(), self.winfo_y()]
            al.salva_estado(st)
        else:
            self._menu.tk_popup(e.x_root, e.y_root)
        self._drag = None


# ================= vigia (thread) =================

def vigia(q, parar, forca):
    st = al.carrega_estado()
    primeira_badge = "vistos_badges" not in st
    st.setdefault("vistos_badges", {})
    cfg = {}

    while not parar.is_set():
        try:
            cfg = al.carrega_config()
            col = checker.coletar(incluir_badges=True)
            camps = [c for c in col["camps"] if al.relevante(c, cfg)]
            ups = [c for c in camps if c.get("status") == "UPCOMING"]
            atv = [c for c in camps if c.get("status") == "ACTIVE"]
            badges = [b for b in col["badges"] if not al.bloqueado(b.get("title"), cfg)]

            CACHE.update(ups=ups, atv=atv, badges=badges,
                         quando=datetime.datetime.now(datetime.timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"))
            escreve_dados_painel()

            vistos = st.setdefault("vistos_upcoming", {})
            avisados = set(st.setdefault("avisados_inicio", []))

            if st.get("primeira_vez"):
                for c in ups:
                    vistos[al.chave(c)] = c.get("start_at") or ""
                st["primeira_vez"] = False

            for c in ups:
                k = al.chave(c)
                if k not in vistos:
                    vistos[k] = c.get("start_at") or ""
                    q.put(("popup", monta_drop(c)))
                    al.discord(cfg, "🔜 %s" % (c.get("game") or "?"),
                               "**%s**\nComeça **%s** · aberto a todos os canais\n%s"
                               % (c.get("name") or "", al.hora_local(c.get("start_at")),
                                  al.resumo_recompensas(c)), al.AZUL,
                               c.get("image") or c.get("game_box"))

            if cfg.get("avisar_quando_comecar", True):
                por_chave = {al.chave(c): c for c in atv}
                for k in list(vistos.keys()):
                    c = por_chave.get(k)
                    if c and k not in avisados:
                        avisados.add(k)
                        st["avisados_inicio"] = sorted(avisados)
                        q.put(("popup", monta_drop(c, comecou=True)))
                        al.discord(cfg, "🟢 %s — começou!" % (c.get("game") or "?"),
                                   "**%s**\nJá dá pra farmar · termina %s\n%s"
                                   % (c.get("name") or "", al.hora_local(c.get("end_at")),
                                      al.resumo_recompensas(c)), al.VERDE,
                                   c.get("image") or c.get("game_box"))

            vb = st["vistos_badges"]
            for b in badges:
                k = chave_badge(b)
                if k in vb:
                    continue
                vb[k] = b.get("start_at") or ""
                if not primeira_badge:
                    q.put(("popup", monta_badge(b)))
                    al.discord(cfg, "🏅 %s" % (b.get("title") or "?"),
                               "Badge chegando · começa **%s**\n%s"
                               % (al.hora_local(b.get("start_at")), b.get("note") or ""),
                               0xF0A83C, (b.get("images") or [None])[0])
            primeira_badge = False

            # badge da bolinha: o que existe agora e o user ainda nao viu no painel
            chaves_atual = {al.chave(c) for c in ups} | {chave_badge(b) for b in badges}
            VISTO["panel"] &= chaves_atual                      # esquece o que ja saiu do ar
            n_novos = len(chaves_atual - VISTO["panel"])
            st["panel_vistos"] = sorted(VISTO["panel"])
            q.put(("atualiza", n_novos))

            existentes = {al.chave(c) for c in camps}
            for k in list(vistos.keys()):
                if k not in existentes and k in avisados:
                    del vistos[k]
            st["avisados_inicio"] = [k for k in avisados if k in vistos or k in existentes]
            corte = (datetime.datetime.now(datetime.timezone.utc)
                     - datetime.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for k in list(vb.keys()):
                if (vb[k] or "9999") < corte:
                    del vb[k]

            al.salva_estado(st)
            al.log("ciclo ok: %d em-breve, %d ativos, %d badges, %d nao-vistos" %
                   (len(ups), len(atv), len(badges), n_novos))
        except Exception as e:
            al.log("erro no ciclo (%s: %s)" % (type(e).__name__, e))

        forca.wait(max(1, int(cfg.get("intervalo_minutos", 5) or 5)) * 60)
        forca.clear()


# ================= bandeja + main =================

def icone_bandeja():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 20, 58, 58], 10, fill=ROXO)
    d.rectangle([28, 20, 36, 58], fill="#0d0d10")
    d.rectangle([6, 32, 58, 38], fill="#0d0d10")
    d.rounded_rectangle([10, 8, 30, 22], 7, outline=ROXO, width=5)
    d.rounded_rectangle([34, 8, 54, 22], 7, outline=ROXO, width=5)
    return img


def exemplo_para_teste(q):
    try:
        if not CACHE["ups"] and not CACHE["badges"]:
            cfg = al.carrega_config()
            col = checker.coletar(incluir_badges=True)
            camps = [c for c in col["camps"] if al.relevante(c, cfg)]
            CACHE.update(ups=[c for c in camps if c["status"] == "UPCOMING"],
                         atv=[c for c in camps if c["status"] == "ACTIVE"],
                         badges=[b for b in col["badges"] if not al.bloqueado(b.get("title"), cfg)],
                         quando=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            escreve_dados_painel()
        if CACHE["ups"]:
            q.put(("popup", monta_drop(CACHE["ups"][0])))
        if CACHE["badges"]:
            q.put(("popup", monta_badge(CACHE["badges"][0])))
    except Exception:
        pass


def main():
    demo = "--demo" in sys.argv

    if not demo:
        trava = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            trava.bind(("127.0.0.1", 58311))
        except OSError:
            al.log("ja tem um Drops Radar rodando; saindo.")
            return

    st0 = al.carrega_estado()
    VISTO["panel"] = set(st0.get("panel_vistos") or [])

    root = tk.Tk()
    root.withdraw()
    q = queue.Queue()
    parar = threading.Event()
    forca = threading.Event()
    viewer = {"p": None}

    def abrir_site(*_):
        p = viewer.get("p")
        if p and p.poll() is None:
            return
        viewer["p"] = subprocess.Popen([PYW, os.path.join(AQUI, "viewer_site.py")], cwd=AQUI)

    def testar(*_):
        threading.Thread(target=exemplo_para_teste, args=(q,), daemon=True).start()

    def sair(icon=None, *_):
        parar.set()
        forca.set()
        p = PAINEL_PROC.get("p")
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        ic = WIDGET.get("icon")
        if ic:
            ic.stop()
        q.put(("sair", None))

    def atualiza_agora(*_):
        forca.set()

    def alterna_bolinha(*_):
        b = WIDGET["bolinha"]
        if b.state() == "withdrawn":
            b.deiconify()
            b.attributes("-topmost", True)
        else:
            b.withdraw()

    WIDGET["bolinha"] = Bolinha(root, abrir_painel, [
        ("Abrir painel", abrir_painel),
        ("Atualizar agora", atualiza_agora),
        ("Abrir site", abrir_site),
        ("Esconder bolinha", alterna_bolinha),
        ("Sair", lambda: sair()),
    ])

    def processa_fila():
        try:
            while True:
                tipo, dado = q.get_nowait()
                if tipo == "sair":
                    root.destroy()
                    return
                if tipo == "popup":
                    cfg = al.carrega_config()
                    Notificacao(root, renderiza_card(dado),
                                segundos=int(cfg.get("notificacao_segundos", 12)))
                elif tipo == "atualiza":
                    b = WIDGET["bolinha"]
                    if b and b.winfo_exists():
                        b.desenha(dado or 0)
                elif tipo == "__painel__":
                    abrir_painel()
        except queue.Empty:
            pass
        root.after(200, processa_fila)

    if demo:
        def demo_seq():
            exemplo_para_teste(q)
            q.put(("atualiza", 2))
            q.put(("__painel__", None))
        threading.Thread(target=demo_seq, daemon=True).start()
        root.after(35000, root.destroy)
        processa_fila()
        root.mainloop()
        return

    menu = pystray.Menu(
        pystray.MenuItem("Painel de drops", lambda *_: q.put(("__painel__", None)), default=True),
        pystray.MenuItem("Mostrar/esconder bolinha", alterna_bolinha),
        pystray.MenuItem("Abrir site", abrir_site),
        pystray.MenuItem("Testar notificação", testar),
        pystray.MenuItem("Atualizar agora", atualiza_agora),
        pystray.MenuItem("Sair", sair),
    )
    icon = pystray.Icon("drops_radar", icone_bandeja(), "Drops Radar", menu)
    WIDGET["icon"] = icon

    threading.Thread(target=icon.run, daemon=True).start()
    threading.Thread(target=vigia, args=(q, parar, forca), daemon=True).start()
    processa_fila()
    root.mainloop()


if __name__ == "__main__":
    main()
