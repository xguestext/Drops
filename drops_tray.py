#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drops Radar - widget de desktop + bandeja.

- BOLINHA sempre visivel POR CIMA de tudo: presentinho + contagem de drops "em breve".
  Arrasta pra onde quiser (posicao fica salva). Passou o MOUSE -> abre o PAINEL.
  Clique = abre/fecha o painel fixo. Botao direito = menu (atualizar/esconder/sair).
- PAINEL local (nada de site): Em breve / Ativos / Badges chegando, igual ao visual
  do site, renderizado aqui no PC com os dados que o vigia ja baixou.
- NOTIFICACOES (cards iguais ao site) empilham EM CIMA da bolinha: 1, 2, 3...
  Some sozinha, mouse em cima pausa, clique fecha.
- Icone na bandeja continua: painel / site / testar / sair. Liga no boot, morre no desligar.

Uso: pythonw drops_tray.py          (normal)
     python  drops_tray.py --demo   (bolinha + painel + 2 notificacoes de exemplo)
"""
import io
import os
import re
import sys
import queue
import ctypes
import socket
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

# dados compartilhados entre vigia (thread) e interface
CACHE = {"ups": [], "atv": [], "badges": [], "quando": None}
THUMBS = {}           # url -> PIL.Image (originalzinha)
WIDGET = {"bolinha": None, "painel": None, "icon": None}

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


def baixa_imagem(url, alvo=None):
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


def thumb_tk(url, letra, alvo, raio=6):
    img = cobre(baixa_imagem(url), alvo) or placeholder(letra, alvo)
    return ImageTk.PhotoImage(arredonda(img, raio))


def _corta(d, txt, f, maxw):
    if d.textlength(txt, font=f) <= maxw:
        return txt
    while txt and d.textlength(txt + "…", font=f) > maxw:
        txt = txt[:-1]
    return txt + "…"


def desenha_presente(d, x, y, t, cor=ROXO):
    """Presentinho vetorial num quadrado t x t a partir de (x, y)."""
    d.rounded_rectangle([x + t * .08, y + t * .30, x + t * .92, y + t * .92], t * .14, fill=cor)
    d.rectangle([x + t * .44, y + t * .30, x + t * .56, y + t * .92], fill=CARD)
    d.rectangle([x + t * .08, y + t * .48, x + t * .92, y + t * .57], fill=CARD)
    d.rounded_rectangle([x + t * .14, y + t * .10, x + t * .46, y + t * .32], t * .10, outline=cor, width=max(2, int(t * .08)))
    d.rounded_rectangle([x + t * .54, y + t * .10, x + t * .86, y + t * .32], t * .10, outline=cor, width=max(2, int(t * .08)))


# ================= notificacao (card igual ao site) =================

def renderiza_card(dado):
    S = 2
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
        if b and b.winfo_exists() and b.state() != "withdrawn":
            # empilha EM CIMA da bolinha
            bx, by = b.winfo_rootx(), b.winfo_rooty()
            x = max(8, min(bx + b.winfo_width() - W, sw - W - 8))
            y = by - 10 - H - ocupado
            if y < 8:
                y = 8
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


# ================= bolinha (widget sempre por cima) =================

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

        self.lbl = tk.Label(self, bg=CHAVE_TRANSP, bd=0)
        self.lbl.pack()
        self.lbl.bind("<ButtonPress-1>", self._press)
        self.lbl.bind("<B1-Motion>", self._move)
        self.lbl.bind("<ButtonRelease-1>", self._solta)
        self.lbl.bind("<Enter>", lambda e: self.after(250, self._hover))
        self._menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TXT,
                             activebackground=ROXO, activeforeground="#fff", bd=0)
        for nome, fn in menu_acoes:
            self._menu.add_command(label=nome, command=fn)
        self.lbl.bind("<Button-3>", lambda e: self._menu.tk_popup(e.x_root, e.y_root))

        st = al.carrega_estado()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = (st.get("widget_pos") or [sw - 120, sh - 170])
        x = max(0, min(int(x), sw - 90))
        y = max(0, min(int(y), sh - 60))
        self.desenha(0)
        self.geometry("+%d+%d" % (x, y))

    def desenha(self, n_up):
        S = 2
        txt = str(n_up)
        f = fonte(15 * S, "bold")
        base_probe = Image.new("RGB", (1, 1))
        wt = ImageDraw.Draw(base_probe).textlength(txt, font=f)
        W = int(56 * S + wt + 18 * S)
        H = 44 * S
        img = Image.new("RGB", (W, H), CHAVE_TRANSP)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, W - 1, H - 1], H // 2, fill=CARD, outline=LINHA, width=S)
        desenha_presente(d, 10 * S, 8 * S, 28 * S)
        d.text((46 * S, H / 2), txt, fill=TXT, font=f, anchor="lm")
        if n_up > 0:
            d.ellipse([W - 14 * S, 6 * S, W - 6 * S, 14 * S], fill=AZUL)
        self._pil = img.resize((W // S, H // S), Image.LANCZOS)
        self._img = ImageTk.PhotoImage(self._pil)
        self.lbl.configure(image=self._img)

    # arrastar
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
            self.ao_clicar()
        self._drag = None

    def _hover(self):
        px, py = self.winfo_pointerxy()
        if (self.winfo_rootx() <= px < self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= py < self.winfo_rooty() + self.winfo_height()):
            self.ao_clicar(hover=True)


# ================= painel local (os drops, igual ao site) =================

class Painel(tk.Toplevel):
    def __init__(self, root, bolinha, fixo=False):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=LINHA)
        self.fixo = fixo
        self.bolinha = bolinha
        self._refs = []

        W, Hmax = 470, 620
        casca = tk.Frame(self, bg=BG)
        casca.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(casca, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(head, text="Drops Radar", font=("Segoe UI", 12, "bold"),
                 fg=TXT, bg=BG).pack(side="left")
        q = CACHE.get("quando")
        atras = ("atualizado há %s" % rel_curto(q)) if q else "carregando…"
        atras = atras.replace("há agora", "agora")
        tk.Label(head, text=atras, font=("Segoe UI", 9), fg=FAINT, bg=BG).pack(side="left", padx=10)
        if fixo:
            fx = tk.Label(head, text="✕", font=("Segoe UI", 11, "bold"), fg=FAINT, bg=BG, cursor="hand2")
            fx.pack(side="right")
            fx.bind("<Button-1>", lambda e: self.destroy())

        # area com rolagem
        self.cv = tk.Canvas(casca, bg=BG, highlightthickness=0, width=W - 2)
        self.cv.pack(fill="both", expand=True)
        self.corpo = tk.Frame(self.cv, bg=BG)
        self.cv.create_window((0, 0), window=self.corpo, anchor="nw", width=W - 2)
        self.corpo.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        for w in (self.cv, self.corpo):
            w.bind("<MouseWheel>", self._roda)

        self._monta()

        self.update_idletasks()
        h = min(Hmax, self.corpo.winfo_reqheight() + 46)
        self.cv.configure(height=h - 46)

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        bx, by = bolinha.winfo_rootx(), bolinha.winfo_rooty()
        x = max(8, min(bx + bolinha.winfo_width() - W, sw - W - 8))
        y = by - h - 10
        if y < 8:
            y = min(by + bolinha.winfo_height() + 10, sh - h - 8)
        self.geometry("%dx%d+%d+%d" % (W, h, x, y))
        self.bind("<Escape>", lambda e: self.destroy())
        if not fixo:
            self.after(400, self._vigia_mouse)

    def _roda(self, e):
        self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def _secao(self, titulo, cor, n):
        f = tk.Frame(self.corpo, bg=BG)
        f.pack(fill="x", padx=14, pady=(10, 4))
        tk.Frame(f, bg=cor, width=8, height=8).pack(side="left", pady=4)
        tk.Label(f, text=" " + titulo, font=("Segoe UI", 9, "bold"), fg=TXT, bg=BG).pack(side="left")
        tk.Label(f, text=" %d" % n, font=("Segoe UI", 9), fg=FAINT, bg=BG).pack(side="left")

    def _linha(self, thumb, cima, meio, baixo, extra=None, extra_cor=AMBAR, h_thumb=(40, 54)):
        row = tk.Frame(self.corpo, bg=CARD)
        row.pack(fill="x", padx=14, pady=3)
        inner = tk.Frame(row, bg=CARD)
        inner.pack(fill="x", padx=10, pady=7)
        img = thumb
        if img is not None:
            self._refs.append(img)
            tk.Label(inner, image=img, bg=CARD, bd=0).pack(side="left", padx=(0, 10))
        tx = tk.Frame(inner, bg=CARD)
        tx.pack(side="left", fill="x", expand=True)
        if cima:
            tk.Label(tx, text=cima, font=("Segoe UI", 8, "bold"), fg=ROXO_LT, bg=CARD,
                     anchor="w").pack(fill="x")
        tk.Label(tx, text=meio, font=("Segoe UI", 10, "bold"), fg=TXT, bg=CARD,
                 anchor="w").pack(fill="x")
        if baixo:
            tk.Label(tx, text=baixo, font=("Segoe UI", 9), fg=DIM, bg=CARD,
                     anchor="w").pack(fill="x")
        if extra:
            tk.Label(inner, text=extra, font=("Segoe UI", 9, "bold"), fg=extra_cor,
                     bg=CARD).pack(side="right", padx=4)

    def _monta(self):
        ups, atv, badges = CACHE["ups"], CACHE["atv"], CACHE["badges"]
        if not ups and not atv and not badges:
            tk.Label(self.corpo, text="Primeira checagem em andamento…\nAbre de novo em alguns segundos.",
                     font=("Segoe UI", 10), fg=DIM, bg=BG, justify="center").pack(pady=30)
            return

        if ups:
            self._secao("EM BREVE", AZUL, len(ups))
            for c in ups:
                th = thumb_tk(c.get("game_box") or c.get("image"), c.get("game"), (40, 54))
                nrec = len(c.get("rewards") or [])
                extra = ("%d min" % c["required_minutes"]) if c.get("required_minutes") else \
                    ("%d rec." % nrec if nrec else None)
                self._linha(th, (c.get("game") or "").upper(),
                            c.get("name") or c.get("game") or "?",
                            "começa em %s · %s" % (rel_curto(c.get("start_at")), data_curta(c.get("start_at"))),
                            extra)
        if badges:
            self._secao("BADGES CHEGANDO", AMBAR, len(badges))
            for b in badges:
                th = thumb_tk((b.get("images") or [None])[0], b.get("title"), (36, 36), raio=8)
                self._linha(th, "BADGE DA TWITCH",
                            (b.get("title") or "?")[:44],
                            "começa em %s · %s" % (rel_curto(b.get("start_at")), data_curta(b.get("start_at"))),
                            None)
        if atv:
            self._secao("ATIVOS AGORA", VERDE, len(atv))
            for c in atv[:40]:
                th = thumb_tk(c.get("game_box") or c.get("image"), c.get("game"), (32, 44))
                self._linha(th, None,
                            c.get("game") or "?",
                            "termina em %s · %s" % (rel_curto(c.get("end_at")), data_curta(c.get("end_at"))),
                            None)
            if len(atv) > 40:
                tk.Label(self.corpo, text="+%d ativos" % (len(atv) - 40), font=("Segoe UI", 9),
                         fg=FAINT, bg=BG).pack(pady=(2, 8))
        tk.Frame(self.corpo, bg=BG, height=8).pack()

    def _vigia_mouse(self):
        """Painel aberto por hover: fecha quando o mouse sai dele e da bolinha."""
        if not self.winfo_exists():
            return
        px, py = self.winfo_pointerxy()

        def dentro(w, folga=24):
            try:
                return (w.winfo_rootx() - folga <= px < w.winfo_rootx() + w.winfo_width() + folga
                        and w.winfo_rooty() - folga <= py < w.winfo_rooty() + w.winfo_height() + folga)
            except tk.TclError:
                return False
        if dentro(self) or dentro(self.bolinha):
            self.after(300, self._vigia_mouse)
        else:
            self.destroy()


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

            # alimenta o painel + pre-baixa as capas (pro hover abrir instantaneo)
            CACHE.update(ups=ups, atv=atv, badges=badges,
                         quando=datetime.datetime.now(datetime.timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"))
            for c in ups + atv[:40]:
                baixa_imagem(c.get("game_box") or c.get("image"))
            for b in badges:
                baixa_imagem((b.get("images") or [None])[0])
            q.put(("atualiza", len(ups)))

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
            al.log("ciclo ok: %d em-breve, %d ativos, %d badges" % (len(ups), len(atv), len(badges)))
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
        if CACHE["ups"] or CACHE["badges"]:
            if CACHE["ups"]:
                q.put(("popup", monta_drop(CACHE["ups"][0])))
            if CACHE["badges"]:
                q.put(("popup", monta_badge(CACHE["badges"][0])))
            return
        col = checker.coletar(incluir_badges=True)
        cfg = al.carrega_config()
        ups = [c for c in col["camps"] if al.relevante(c, cfg) and c.get("status") == "UPCOMING"] \
            or [c for c in col["camps"] if al.relevante(c, cfg)]
        if ups:
            q.put(("popup", monta_drop(ups[0])))
        if col["badges"]:
            q.put(("popup", monta_badge(col["badges"][0])))
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
        ic = WIDGET.get("icon")
        if ic:
            ic.stop()
        q.put(("sair", None))

    def alterna_painel(hover=False):
        p = WIDGET.get("painel")
        if p and p.winfo_exists():
            if hover:
                return
            p.destroy()
            WIDGET["painel"] = None
            return
        WIDGET["painel"] = Painel(root, WIDGET["bolinha"], fixo=not hover)

    def atualiza_agora(*_):
        forca.set()

    def alterna_bolinha(*_):
        b = WIDGET["bolinha"]
        if b.state() == "withdrawn":
            b.deiconify()
            b.attributes("-topmost", True)
        else:
            b.withdraw()

    WIDGET["bolinha"] = Bolinha(root, alterna_painel, [
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
                if tipo == "atualiza":
                    b = WIDGET["bolinha"]
                    if b and b.winfo_exists():
                        b.desenha(dado or 0)
        except queue.Empty:
            pass
        root.after(200, processa_fila)

    if demo:
        def demo_seq():
            try:
                cfg = al.carrega_config()
                col = checker.coletar(incluir_badges=True)
                camps = [c for c in col["camps"] if al.relevante(c, cfg)]
                CACHE.update(ups=[c for c in camps if c["status"] == "UPCOMING"],
                             atv=[c for c in camps if c["status"] == "ACTIVE"],
                             badges=[b for b in col["badges"] if not al.bloqueado(b.get("title"), cfg)],
                             quando=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                for c in CACHE["ups"] + CACHE["atv"][:40]:
                    baixa_imagem(c.get("game_box") or c.get("image"))
                for b in CACHE["badges"]:
                    baixa_imagem((b.get("images") or [None])[0])
                q.put(("atualiza", len(CACHE["ups"])))
                q.put(("demo_painel", None))
                exemplo_para_teste(q)
            except Exception as e:
                al.log("demo: %s" % e)
        def processa_demo():
            try:
                while True:
                    tipo, dado = q.get_nowait()
                    if tipo == "popup":
                        Notificacao(root, renderiza_card(dado), segundos=14)
                    if tipo == "atualiza":
                        WIDGET["bolinha"].desenha(dado or 0)
                    if tipo == "demo_painel":
                        WIDGET["painel"] = Painel(root, WIDGET["bolinha"], fixo=True)
            except queue.Empty:
                pass
            root.after(200, processa_demo)
        threading.Thread(target=demo_seq, daemon=True).start()
        root.after(35000, root.destroy)
        processa_demo()
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

    def processa_fila2():
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
                    alterna_painel()
        except queue.Empty:
            pass
        root.after(200, processa_fila2)

    threading.Thread(target=icon.run, daemon=True).start()
    threading.Thread(target=vigia, args=(q, parar, forca), daemon=True).start()
    processa_fila2()
    root.mainloop()


if __name__ == "__main__":
    main()
