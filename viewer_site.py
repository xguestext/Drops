# -*- coding: utf-8 -*-
"""Janela do Drops Radar: abre o site numa janela propria (sem barra de navegador).
Se o WebView2 nao existir, cai pro navegador padrao."""
SITE = "https://xguestext.github.io/Drops/"

try:
    import webview
    webview.create_window("Drops Radar", SITE, width=1180, height=820,
                          background_color="#0d0d10", min_size=(760, 520))
    webview.start()
except Exception:
    import webbrowser
    webbrowser.open(SITE)
