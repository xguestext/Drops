# -*- coding: utf-8 -*-
"""Abre o Drops Radar como APLICATIVO (janela propria, sem cara de navegador).

Ordem: 1) Edge em modo app (todo Windows 11 tem)  2) Chrome em modo app
       3) pywebview  4) navegador comum (ultimo recurso).
Modo app = janela sem abas/sem barra de endereco, icone proprio na barra."""
import os
import sys
import subprocess

SITE = "https://xguestext.github.io/Drops/"


def acha(*caminhos):
    for c in caminhos:
        if c and os.path.exists(c):
            return c
    return None


pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
pf = os.environ.get("ProgramFiles", r"C:\Program Files")
lad = os.environ.get("LOCALAPPDATA", "")

edge = acha(os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"))
chrome = acha(os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
              os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
              os.path.join(lad, r"Google\Chrome\Application\chrome.exe"))

nav = edge or chrome
if nav:
    p = subprocess.Popen([nav, "--app=" + SITE, "--window-size=1180,860"])
    try:
        p.wait()
    except KeyboardInterrupt:
        pass
    sys.exit(0)

try:
    import webview
    webview.create_window("Drops Radar", SITE, width=1180, height=820,
                          background_color="#0d0d10", min_size=(760, 520))
    webview.start()
except Exception:
    import webbrowser
    webbrowser.open(SITE)
