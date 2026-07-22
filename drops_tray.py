#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drops Radar - programa de bandeja (fica na setinha perto do relogio).

- Clique no icone         -> abre o site numa janela propria (viewer_site.py)
- Botao direito           -> menu: Abrir / Testar notificacao / Sair
- Vigia em segundo plano  -> drop novo EM BREVE (aberto a todos) ou BADGE nova chegando:
                             notificacao CUSTOM bonita (capa do jogo, quando comeca, o que e,
                             etiqueta DROP/BADGE). Some sozinha apos N segundos, PAUSA com o
                             mouse em cima e FECHA no clique. Discord junto, se tiver webhook.
- Liga com o Windows (bat na pasta Inicializar) e morre no desligar ou no Sair.

Uso: pythonw drops_tray.py          (normal, invisivel)
     python  drops_tray.py --demo   (so mostra 2 notificacoes de exemplo e sai)
"""
import io
import os
import sys
import queue
import ctypes
import socket
import threading
import subprocess
import datetime
import urllib.request
import tkinter as tk
import tkinter.font as tkfont

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import checker            # noqa: E402
import alerta_drops as al  # noqa: E402  (config/estado/discord/formatacao)

from PIL import Image, ImageDraw, ImageTk  # noqa: E402
import pystray             # noqa: E402

SITE = "https://xguestext.github.io/Drops/"
PYW = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python314\pythonw.exe")
if not os.path.exists(PYW):
    PYW = "pythonw"

# cores (mesmas do site)
BG, CARD, LINHA = "#0d0d10", "#17171b", "#2a2a32"
TXT, DIM, FAINT = "#efeff1", "#b0b0bb", "#787885"
AZUL, VERDE, AMBAR, ROXO = "#3ea6ff", "#2ec16a", "#f0a83c", "#9147ff"

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # notificacao nitida em tela escalada
except Exception:
    pass


def rel_curto(iso):
    """'em 2 dias' / 'em 5 h' / 'em 32 min'"""
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        s = (dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if s <= 0:
            return "agora"
        if s < 3600:
            return "em %d min" % round(s / 60)
        if s < 86400:
            return "em %d h" % round(s / 3600)
        d = round(s / 86400)
        return "em %d dia%s" % (d, "s" if d > 1 else "")
    except Exception:
        return ""


def baixa_imagem(url, alvo):
    """Baixa e recorta a imagem pro tamanho do card. None se falhar."""
    if not url:
        return None
    url = url.replace("{width}", "144").replace("{height}", "192")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "drops-radar-tray/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            img = Image.open(io.BytesIO(r.read())).convert("RGB")
        img.thumbnail((alvo[0] * 2, alvo[1] * 2))
        img = img.resize(alvo, Image.LANCZOS)
        return img
    except Exception:
        return None


def imagem_placeholder(letra, alvo, cor=ROXO):
    img = Image.new("RGB", alvo, "#1e1e24")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, alvo[0] - 1, alvo[1] - 1], outline="#2a2a32")
    try:
        from PIL import ImageFont
        f = ImageFont.truetype("segoeuib.ttf", int(alvo[1] * 0.42))
    except Exception:
        f = None
    d.text((alvo[0] / 2, alvo[1] / 2), (letra or "?")[:1].upper(), fill=cor, font=f, anchor="mm")
    return img


# ---------------- notificacao custom ----------------

class Notificacao(tk.Toplevel):
    ABERTAS = []

    def __init__(self, root, titulo, etiqueta, cor, linha1, linha2, pil_img, segundos=12):
        super().__init__(root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=LINHA)

        self.restante = int(segundos * 10)   # decimos de segundo
        self.pausado = False

        W, H = 400, 116
        borda = tk.Frame(self, bg=LINHA)
        borda.pack(fill="both", expand=True)
        faixa = tk.Frame(borda, bg=cor, width=4)
        faixa.pack(side="left", fill="y")
        card = tk.Frame(borda, bg=CARD)
        card.pack(side="left", fill="both", expand=True, padx=(0, 1), pady=1)

        f_tit = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        f_tag = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        f_txt = tkfont.Font(family="Segoe UI", size=9)

        self._img = ImageTk.PhotoImage(pil_img)
        lbl_img = tk.Label(card, image=self._img, bg=CARD, bd=0)
        lbl_img.pack(side="left", padx=(12, 10), pady=12)

        corpo = tk.Frame(card, bg=CARD)
        corpo.pack(side="left", fill="both", expand=True, pady=10)

        topo = tk.Frame(corpo, bg=CARD)
        topo.pack(fill="x", anchor="w")
        tk.Label(topo, text=titulo, font=f_tit, fg=TXT, bg=CARD, anchor="w").pack(side="left")
        tk.Label(topo, text=" " + etiqueta + " ", font=f_tag, fg="#101014", bg=cor).pack(side="left", padx=8)

        tk.Label(corpo, text=linha1, font=f_txt, fg=DIM, bg=CARD, anchor="w",
                 wraplength=280, justify="left").pack(fill="x", anchor="w", pady=(3, 0))
        tk.Label(corpo, text=linha2, font=f_txt, fg=FAINT, bg=CARD, anchor="w",
                 wraplength=280, justify="left").pack(fill="x", anchor="w", pady=(2, 0))

        # posicao: canto inferior direito, empilhando pra cima
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        ocupado = sum(n.winfo_height() + 10 for n in Notificacao.ABERTAS if n.winfo_exists())
        x = sw - W - 16
        y = sh - 56 - H - ocupado
        self.geometry("%dx%d+%d+%d" % (W, H, x, y))
        Notificacao.ABERTAS.append(self)

        # clique fecha; mouse em cima pausa o relogio
        for w in self._todos_widgets(self):
            w.bind("<Button-1>", lambda e: self.fechar())
            w.bind("<Enter>", lambda e: self._pausa(True))
            w.bind("<Leave>", lambda e: self._pausa(False))

        # fade in
        self.attributes("-alpha", 0.0)
        self._fade(0.0, +0.12)
        self.after(100, self._tic)

    def _todos_widgets(self, w):
        yield w
        for c in w.winfo_children():
            yield from self._todos_widgets(c)

    def _pausa(self, v):
        self.pausado = v

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
                self._fade(1.0, -0.12)
                return
        self.after(100, self._tic)

    def fechar(self):
        self._fade(1.0, -0.25)

    def _some(self):
        try:
            Notificacao.ABERTAS.remove(self)
        except ValueError:
            pass
        self.destroy()


# ---------------- montagem dos avisos ----------------

def notif_drop(q, c, comecou=False):
    img = baixa_imagem(c.get("game_box") or c.get("image"), (64, 86)) \
        or imagem_placeholder(c.get("game"), (64, 86))
    if comecou:
        etiqueta, cor = "DROP · COMEÇOU", VERDE
        linha1 = "Já dá pra farmar · termina %s" % al.hora_local(c.get("end_at"))
    else:
        etiqueta, cor = "DROP · EM BREVE", AZUL
        linha1 = "Começa %s (%s) · todos os canais" % (
            al.hora_local(c.get("start_at")), rel_curto(c.get("start_at")))
    q.put(("popup", dict(titulo=c.get("game") or "?", etiqueta=etiqueta, cor=cor,
                         linha1=linha1, linha2=al.resumo_recompensas(c, 3), img=img)))


def notif_badge(q, b):
    img = baixa_imagem((b.get("images") or [None])[0], (56, 56))
    img = img or imagem_placeholder(b.get("title"), (56, 56), AMBAR)
    # centraliza badge menor num quadro do mesmo tamanho do card de drop
    quadro = Image.new("RGB", (64, 86), CARD)
    quadro.paste(img, (4, 15))
    q.put(("popup", dict(titulo=(b.get("title") or "?")[:34], etiqueta="BADGE · CHEGANDO", cor=AMBAR,
                         linha1="Começa %s (%s)" % (al.hora_local(b.get("start_at")), rel_curto(b.get("start_at"))),
                         linha2=(b.get("note") or "Badge global de evento da Twitch")[:90], img=quadro)))


def chave_badge(b):
    import re
    return re.sub(r"[^a-z0-9]", "", (b.get("title") or "").lower()) + "|" + (b.get("start_at") or "")[:10]


# ---------------- vigia (thread) ----------------

def vigia(q, parar):
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
            vistos = st.setdefault("vistos_upcoming", {})
            avisados = set(st.setdefault("avisados_inicio", []))

            if st.get("primeira_vez"):
                for c in ups:
                    vistos[al.chave(c)] = c.get("start_at") or ""
                st["primeira_vez"] = False

            # drops novos "em breve"
            for c in ups:
                k = al.chave(c)
                if k not in vistos:
                    vistos[k] = c.get("start_at") or ""
                    notif_drop(q, c)
                    al.discord(cfg, "🔜 %s" % (c.get("game") or "?"),
                               "**%s**\nComeça **%s** · aberto a todos os canais\n%s"
                               % (c.get("name") or "", al.hora_local(c.get("start_at")),
                                  al.resumo_recompensas(c)), al.AZUL,
                               c.get("image") or c.get("game_box"))

            # vigiado comecou
            if cfg.get("avisar_quando_comecar", True):
                por_chave = {al.chave(c): c for c in atv}
                for k in list(vistos.keys()):
                    c = por_chave.get(k)
                    if c and k not in avisados:
                        avisados.add(k)
                        st["avisados_inicio"] = sorted(avisados)
                        notif_drop(q, c, comecou=True)
                        al.discord(cfg, "🟢 %s — começou!" % (c.get("game") or "?"),
                                   "**%s**\nJá dá pra farmar · termina %s\n%s"
                                   % (c.get("name") or "", al.hora_local(c.get("end_at")),
                                      al.resumo_recompensas(c)), al.VERDE,
                                   c.get("image") or c.get("game_box"))

            # badges novas chegando
            vb = st["vistos_badges"]
            for b in col["badges"]:
                if al.bloqueado(b.get("title"), cfg):
                    continue
                k = chave_badge(b)
                if k in vb:
                    continue
                vb[k] = b.get("start_at") or ""
                if not primeira_badge:
                    notif_badge(q, b)
                    al.discord(cfg, "🏅 %s" % (b.get("title") or "?"),
                               "Badge chegando · começa **%s**\n%s"
                               % (al.hora_local(b.get("start_at")), b.get("note") or ""),
                               0xF0A83C, (b.get("images") or [None])[0])
            primeira_badge = False

            # limpeza de vistos mortos
            existentes = {al.chave(c) for c in camps}
            for k in list(vistos.keys()):
                if k not in existentes and k in avisados:
                    del vistos[k]
            st["avisados_inicio"] = [k for k in avisados if k in vistos or k in existentes]
            agora10 = (datetime.datetime.now(datetime.timezone.utc)
                       - datetime.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for k in list(vb.keys()):
                if (vb[k] or "9999") < agora10:
                    del vb[k]

            al.salva_estado(st)
            al.log("ciclo ok: %d em-breve, %d ativos, %d badges" %
                   (len(ups), len(atv), len(col["badges"])))
        except Exception as e:
            al.log("erro no ciclo (%s: %s)" % (type(e).__name__, e))

        parar.wait(max(1, int(cfg.get("intervalo_minutos", 5) or 5)) * 60)


# ---------------- bandeja ----------------

def icone_bandeja():
    """Presentinho roxo (drop) desenhado na mao."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 20, 58, 58], 10, fill=ROXO)
    d.rectangle([28, 20, 36, 58], fill="#0d0d10")
    d.rectangle([6, 32, 58, 38], fill="#0d0d10")
    d.rounded_rectangle([10, 8, 30, 22], 7, outline=ROXO, width=5)
    d.rounded_rectangle([34, 8, 54, 22], 7, outline=ROXO, width=5)
    return img


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
    viewer = {"p": None}

    def abrir(*_):
        p = viewer.get("p")
        if p and p.poll() is None:
            return
        viewer["p"] = subprocess.Popen([PYW, os.path.join(AQUI, "viewer_site.py")], cwd=AQUI)

    def testar(*_):
        fake = {"game": "Rust", "name": "Twitch Drops - Round 33", "status": "UPCOMING",
                "start_at": (datetime.datetime.now(datetime.timezone.utc)
                             + datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_at": None, "game_box": None, "image": None,
                "rewards": [{"name": "Frontier Hoodie"}, {"name": "Frontier Pants"},
                            {"name": "Frontier Boots"}, {"name": "Frontier Gloves"}]}
        notif_drop(q, fake)
        notif_badge(q, {"title": "TwitchCon 2027 Berlin", "start_at": fake["start_at"],
                        "note": "Badge global de evento da Twitch", "images": []})

    def sair(icon=None, *_):
        parar.set()
        if icon:
            icon.stop()
        q.put(("sair", None))

    def processa_fila():
        try:
            while True:
                tipo, dado = q.get_nowait()
                if tipo == "sair":
                    root.destroy()
                    return
                if tipo == "popup":
                    cfg = al.carrega_config()
                    Notificacao(root, dado["titulo"], dado["etiqueta"], dado["cor"],
                                dado["linha1"], dado["linha2"], dado["img"],
                                segundos=int(cfg.get("notificacao_segundos", 12)))
        except queue.Empty:
            pass
        root.after(200, processa_fila)

    if demo:
        testar()
        root.after(20000, root.destroy)
        processa_fila()
        root.mainloop()
        return

    menu = pystray.Menu(
        pystray.MenuItem("Abrir Drops Radar", abrir, default=True),
        pystray.MenuItem("Testar notificação", testar),
        pystray.MenuItem("Sair", sair),
    )
    icon = pystray.Icon("drops_radar", icone_bandeja(), "Drops Radar", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    threading.Thread(target=vigia, args=(q, parar), daemon=True).start()

    processa_fila()
    root.mainloop()


if __name__ == "__main__":
    main()
