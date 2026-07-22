# Drops Radar

Site estático + grátis que lista as campanhas de **drops da Twitch** — **só as abertas a
qualquer streamer** (campanhas fechadas de canais específicos são descartadas e nem aparecem) —
separando **item de jogo** de **badge/emote/plataforma**.

- **Fontes (todas de terceiros, sem token/login/anti-bot — o checador NUNCA toca a Twitch):**
  - **drops de item:** [sunkwi](https://twitch-drops-api.sunkwi.com/) (ativos) + [fenris](https://twitch-drops.fenrisapps.com/campaigns) (em breve) + [twitchdrops.app](https://twitchdrops.app/) (preenche lacunas). Fundidas por id + chave difusa (jogo+dia).
  - **badges chegando:** [streamdatabase.com/events](https://www.streamdatabase.com/events) (eventos de badge global — categoria à parte dos drops).
  - Motivo de várias fontes: cada agregador espelha a GQL da Twitch mas **perde campanhas diferentes**; juntando, o site fica mais completo. Nenhuma fonte pública antecede a Twitch (a origem é a GQL dela).
- **Checador** (`checker.py`): roda no **GitHub Actions** a cada 30 min, filtra e escreve `data/drops.json`.
- **Site** (`index.html`): página única, sem build, lê o JSON e se atualiza sozinha a cada 5 min.
- Hospedado no **GitHub Pages** → abre de qualquer PC.

---

## Passo a passo (uma vez só)

1. **Repositório** já criado e com os arquivos.

2. **Ligar o GitHub Pages:** Settings → Pages → *Build and deployment* →
   Source: **Deploy from a branch** → Branch: **main** / **/ (root)** → Save.
   O site fica em `https://SEU_USUARIO.github.io/NOME_DO_REPO/`.

3. **Rodar a primeira vez:** aba **Actions** → *Atualizar drops* → **Run workflow**.
   Em ~1 min ele commita o `data/drops.json` e o site mostra os drops. Depois roda sozinho a cada 30 min.

Não precisa de nenhum segredo/token. (Se você tinha criado o secret `TWITCH_OAUTH` numa versão
anterior, pode apagar — não é mais usado.)

---

## Como ele decide

| Eixo | Valor | O que acontece |
|------|-------|----------------|
| Disponibilidade | **Aberto** (todos os canais) | `allow.channels` vazio → **é o que o site mostra** |
| | **Fechado** (canais específicos) | `allow.channels` tem lista → **descartado** |
| Status | **Em breve** / **Ativo** | UPCOMING vem no topo; EXPIRED é descartado |
| Recompensa | **Item de jogo** | não bate nas pistas de plataforma |
| | **Badge/plataforma** | nome bate em badge/emote/sub/bits/etc → filtrável no site |

Pistas de "plataforma": `PLATFORM_HINTS` no `checker.py`.

## Notas

- **Fotos:** capa do jogo e imagem de cada recompensa vêm do CDN de imagens da Twitch
  (`static-cdn.jtvnw.net`). São carregadas pelo seu navegador ao abrir o site (tráfego de
  imagem anônimo, não é chamada de API).
- **"Em breve":** aparece quando algum dev publica uma campanha com data futura. Na maior parte
  do tempo os drops entram já como *ativos*, então essa seção fica vazia com frequência — é normal.
- Se a fonte de terceiro sair do ar, o site mostra um aviso e mantém o último dado.
