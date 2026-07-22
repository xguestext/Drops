#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alerta local de drops da Twitch (roda no SEU pc, em loop).

- Usa o MESMO motor de fontes do site (checker.coletar) -> so terceiros, NUNCA toca a Twitch.
- Drop novo "EM BREVE" aberto a todos  -> toast no Windows + mensagem no Discord (webhook).
- Drop vigiado COMECOU                  -> outro aviso (desligavel na config).
- Lista de exclusao por jogo (ex.: Albion Online, Black Desert) na alerta_config.json.

Uso:
  python alerta_drops.py            roda em loop (Ctrl+C para sair)
  python alerta_drops.py --uma-vez  roda 1 ciclo e sai
  python alerta_drops.py --teste    dispara um toast + discord de teste e sai

Config (alerta_config.json, criada no 1o uso):
  discord_webhook          URL do webhook (vazio = so toast)
  excluir_jogos            lista de jogos ignorados (contem, sem acento/caixa)
  intervalo_minutos        de quanto em quanto tempo checa (padrao 5)
  avisar_quando_comecar    avisa quando um "em breve" vira ativo (padrao true)
  toast / discord          liga/desliga cada canal de aviso
  incluir_badges_plataforma  alertar tb campanhas tipo badge/emote (padrao false)
"""
import json
import os
import re
import sys
import time
import base64
import argparse
import datetime
import subprocess
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import checker  # noqa: E402  (motor de fontes do site)

CONFIG_PATH = os.path.join(AQUI, "alerta_config.json")
ESTADO_PATH = os.path.join(AQUI, "alerta_estado.json")
SITE = "https://xguestext.github.io/Drops/"

CONFIG_PADRAO = {
    "discord_webhook": "",
    "excluir_jogos": ["Albion Online", "Black Desert"],
    "intervalo_minutos": 5,
    "avisar_quando_comecar": True,
    "toast": True,
    "discord": True,
    "incluir_badges_plataforma": False,
}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%d/%m %H:%M:%S"), msg), flush=True)


# ---------------- config / estado ----------------

def carrega_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(CONFIG_PADRAO, f, ensure_ascii=False, indent=2)
        log("criei a config padrao em " + CONFIG_PATH)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = dict(CONFIG_PADRAO)
        cfg.update(json.load(f))
        return cfg


def carrega_estado():
    if os.path.exists(ESTADO_PATH):
        with open(ESTADO_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"vistos_upcoming": {}, "avisados_inicio": [], "primeira_vez": True}


def salva_estado(st):
    with open(ESTADO_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


# ---------------- filtros ----------------

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def bloqueado(game, cfg):
    g = _norm(game)
    return any(_norm(x) and _norm(x) in g for x in cfg.get("excluir_jogos") or [])


def chave(c):
    return c.get("id") or ("%s|%s" % (_norm(c.get("game")), (c.get("start_at") or "")[:10]))


def relevante(c, cfg):
    if c.get("availability") != "open":       # so aberto a todos (defesa extra)
        return False
    if bloqueado(c.get("game"), cfg):
        return False
    if c.get("reward_type") != "game" and not cfg.get("incluir_badges_plataforma"):
        return False
    return True


# ---------------- formatacao ----------------

def hora_local(iso):
    if not iso:
        return "?"
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return iso[:16]


def resumo_recompensas(c, limite=4):
    nomes = [r.get("name") for r in (c.get("rewards") or []) if r.get("name")]
    extra = len(nomes) - limite
    txt = ", ".join(nomes[:limite])
    if extra > 0:
        txt += " +%d" % extra
    return txt or "?"


# ---------------- avisos: toast ----------------

def toast(titulo, msg):
    ps = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $xml.GetElementsByTagName('text')
$t.Item(0).AppendChild($xml.CreateTextNode('%s')) > $null
$t.Item(1).AppendChild($xml.CreateTextNode('%s')) > $null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$appid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appid).Show($toast)
""" % (titulo.replace("'", "''"), msg.replace("'", "''"))
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-EncodedCommand", enc],
            capture_output=True, timeout=30, creationflags=0x08000000)  # CREATE_NO_WINDOW
        return True
    except Exception as e:
        log("toast falhou: %s" % e)
        return False


# ---------------- avisos: discord ----------------

def discord(cfg, titulo, descricao, cor, imagem=None):
    url = (cfg.get("discord_webhook") or "").strip()
    if not url or not cfg.get("discord", True):
        return False
    embed = {"title": titulo, "description": descricao, "color": cor,
             "url": SITE, "footer": {"text": "Drops Radar"}}
    if imagem:
        embed["thumbnail"] = {"url": imagem}
    body = json.dumps({"username": "Drops Radar", "embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "drops-radar-alerta/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
        return True
    except Exception as e:
        log("discord falhou: %s" % e)
        return False


AZUL, VERDE, ROXO = 0x3EA6FF, 0x2EC16A, 0x9147FF


def avisa_novo(cfg, c):
    quando = hora_local(c.get("start_at"))
    rec = resumo_recompensas(c)
    if cfg.get("toast", True):
        toast("Drop chegando: %s" % (c.get("game") or "?"),
              "Comeca %s - %s" % (quando, rec))
    discord(cfg, "🔜 %s" % (c.get("game") or "?"),
            "**%s**\nComeça **%s** · aberto a todos os canais\n%s"
            % (c.get("name") or "", quando, rec),
            AZUL, c.get("image") or c.get("game_box"))
    log("AVISO novo em-breve: %s (%s)" % (c.get("game"), quando))


def avisa_comecou(cfg, c):
    rec = resumo_recompensas(c)
    if cfg.get("toast", True):
        toast("Drop COMECOU: %s" % (c.get("game") or "?"),
              "Ja da pra farmar - %s" % rec)
    discord(cfg, "🟢 %s — começou!" % (c.get("game") or "?"),
            "**%s**\nJá dá pra farmar · termina %s\n%s"
            % (c.get("name") or "", hora_local(c.get("end_at")), rec),
            VERDE, c.get("image") or c.get("game_box"))
    log("AVISO comecou: %s" % c.get("game"))


# ---------------- ciclo ----------------

def ciclo(cfg, st):
    col = checker.coletar(incluir_badges=False)
    camps = [c for c in col["camps"] if relevante(c, cfg)]
    if col["erros"]:
        log("fontes com erro (seguindo com o resto): %s" % "; ".join(col["erros"]))
    if not col["camps"]:
        log("nenhuma fonte respondeu; tento de novo no proximo ciclo")
        return

    ups = [c for c in camps if c.get("status") == "UPCOMING"]
    atv = [c for c in camps if c.get("status") == "ACTIVE"]
    vistos = st.setdefault("vistos_upcoming", {})
    avisados = set(st.setdefault("avisados_inicio", []))

    if st.get("primeira_vez"):
        # 1a rodada: nao spamma o que ja existe; so registra e confirma que ligou.
        for c in ups:
            vistos[chave(c)] = c.get("start_at") or ""
        st["primeira_vez"] = False
        if cfg.get("toast", True):
            toast("Alerta de drops ligado",
                  "Vigiando %d em breve e %d ativos (abertos a todos)" % (len(ups), len(atv)))
        discord(cfg, "✅ Alerta de drops ligado",
                "Vigiando **%d em breve** e **%d ativos** (abertos a todos).\nExcluídos: %s"
                % (len(ups), len(atv), ", ".join(cfg.get("excluir_jogos") or []) or "—"),
                ROXO)
        log("primeira rodada: %d em-breve registrados sem alerta" % len(ups))
        salva_estado(st)
        return

    # novos "em breve"
    for c in ups:
        k = chave(c)
        if k not in vistos:
            vistos[k] = c.get("start_at") or ""
            avisa_novo(cfg, c)

    # vigiados que comecaram
    if cfg.get("avisar_quando_comecar", True):
        ativos_por_chave = {chave(c): c for c in atv}
        for k in list(vistos.keys()):
            if k in avisados:
                continue
            c = ativos_por_chave.get(k)
            if c:
                avisados.add(k)
                st["avisados_inicio"] = sorted(avisados)
                avisa_comecou(cfg, c)

    # limpeza: vistos que nao existem mais em nenhuma lista ha muito tempo
    existentes = {chave(c) for c in camps}
    for k in list(vistos.keys()):
        if k not in existentes and k in avisados:
            del vistos[k]
    st["avisados_inicio"] = [k for k in avisados if k in vistos or k in existentes]

    salva_estado(st)
    log("ciclo ok: %d em-breve (vigiados %d), %d ativos" % (len(ups), len(vistos), len(atv)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--teste", action="store_true")
    args = ap.parse_args()

    cfg = carrega_config()

    if args.teste:
        ok_t = toast("Teste do alerta de drops", "Se voce esta vendo isso, o toast funciona.") if cfg.get("toast", True) else False
        ok_d = discord(cfg, "🧪 Teste do alerta de drops",
                       "Webhook funcionando. Os avisos virão neste canal.", ROXO)
        log("teste: toast=%s discord=%s%s" % (ok_t, ok_d,
            "" if cfg.get("discord_webhook") else " (webhook vazio na config)"))
        return

    st = carrega_estado()
    if args.uma_vez:
        ciclo(cfg, st)
        return

    log("vigia ligado. intervalo: %s min. excluidos: %s" % (
        cfg.get("intervalo_minutos"), ", ".join(cfg.get("excluir_jogos") or []) or "-"))
    while True:
        try:
            cfg = carrega_config()          # pega mudancas na config sem reiniciar
            ciclo(cfg, st)
        except Exception as e:
            log("erro no ciclo (%s: %s); sigo no proximo" % (type(e).__name__, e))
        time.sleep(max(1, int(cfg.get("intervalo_minutos", 5))) * 60)


if __name__ == "__main__":
    main()
