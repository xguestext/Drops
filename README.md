# Drops Radar

Site estático + grátis que lista as campanhas de **drops da Twitch** — **só as abertas a
qualquer streamer** (campanhas fechadas de canais específicos são descartadas pelo checador
e nem aparecem) — separando **item de jogo** de **badge/emote/plataforma**.

- **Checador** (`checker.py`): roda no **GitHub Actions** (nunca na sua máquina), busca os
  drops via GQL e escreve `data/drops.json`.
- **Site** (`index.html`): página única, sem build, lê o JSON e se atualiza sozinha a cada 5 min.
- Hospedado no **GitHub Pages** → abre de qualquer PC.

> ⚠️ O checador **só deve rodar no GitHub**, nunca localmente: rodar na sua máquina bateria
> em `gql.twitch.tv` pelo seu IP real.

---

## Passo a passo (uma vez só)

1. **Crie um repositório PÚBLICO** no GitHub (ex.: `drops-radar`) e suba estes arquivos.
   (Público é seguro: não tem segredo nos arquivos — o token vai separado, no passo 3.)

2. **Ligue o GitHub Pages:** Settings → Pages → *Build and deployment* →
   Source: **Deploy from a branch** → Branch: **main** / **/ (root)** → Save.
   Em ~1 min o site fica em `https://SEU_USUARIO.github.io/drops-radar/`.

3. **Adicione o token** (a lista de drops é por usuário, então precisa de uma conta logada —
   use uma conta **descartável**, nunca a sua principal e nunca uma conta de bot):
   - Faça login dessa conta em `twitch.tv` no navegador.
   - F12 → **Application** → **Cookies** → `https://www.twitch.tv` → copie o valor de **`auth-token`**
     (um código de ~30 caracteres).
   - No repo: Settings → **Secrets and variables** → **Actions** → **New repository secret** →
     Nome: `TWITCH_OAUTH` · Valor: o token colado. Salve.

4. **Rode pela primeira vez:** aba **Actions** → *Atualizar drops* → **Run workflow**.
   Em ~1 min ele commita o `data/drops.json` e o site passa a mostrar os drops.
   Depois disso roda sozinho a cada 30 min.

---

## Como ele decide

| Eixo | Valor | Como é detectado |
|------|-------|------------------|
| Disponibilidade | **Aberto** (todos os canais) | `allow.channels` vazio → é o que o site mostra |
| | **Fechado** (canais específicos) | `allow.channels` tem lista → **descartado, nem entra no site** |
| Recompensa | **Item de jogo** | recompensas não batem nas pistas de plataforma |
| | **Badge/plataforma** | nome bate em badge/emote/sub/bits/etc |

As pistas de "plataforma" ficam em `PLATFORM_HINTS` no `checker.py` — fácil de afinar.

## Notas

- O `auth-token` é a sessão da conta (trate como senha). Fica **só** no Secret, nunca nos arquivos.
  Se um dia os drops pararem de atualizar com "currentUser vazio", o token expirou — repita o passo 3.
- Cron do GitHub é em **UTC** e pode atrasar alguns minutos sob carga (irrelevante pra drops).
- Todo o tráfego pra Twitch sai do **IP do GitHub**, nunca da sua máquina.
