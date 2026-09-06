# Drops Radar

Site estático + grátis que lista as campanhas de **drops da Twitch** — **só as abertas a
qualquer streamer** (campanhas fechadas de canais específicos são descartadas e nem aparecem) —
separando **item de jogo** de **badge/emote/plataforma**.

- **Fonte: a GQL da Twitch, direto** (desde 06/09/2026 — sem agregador de terceiro, sem login, sem token).
  - **Como:** o checador pergunta à Twitch **quais canais estão ao vivo com drop ligado** em cada
    categoria e, para uma amostra desses canais (grandes **e** pequenos), **o que quem assiste ali
    ganha** — é a mesma consulta que o player usa pra desenhar o aviso *"Drops habilitados"*.
    Cada campanha listada aqui foi vista na resposta de um canal real, ao vivo, naquele minuto.
  - **Por que mudou:** o `twitchdrops.app` (raspagem de HTML) publicou *"Minecraft — Amethyst Drone"*,
    que a Twitch não tinha. O bot acreditou, abriu live e contratou 61 viewers pra 1 pessoa real.
    Perguntada direto no mesmo minuto, a Twitch dizia o contrário: os 13 canais de Minecraft com
    `DropsEnabled` tinham só **badge do próprio canal**. Intermediário erra e não avisa.
  - **Peneira (tudo campo da própria campanha, nada de amostragem):**
    - `allow` — **aberta a todos** (`isEnabled: false`; na página da Twitch: *"Go to a participating live
      channel"*) ou **só canais convidados** (`isEnabled: true` + lista; na página: *"including playapex,
      NiceWigg... and more"*). Fechada não entra. Em 06/09 o ALGS do Apex (161 convidados) e o ZEVENT (338)
      tinham passado por aparecerem em vários canais — a lista de permitidos é o que prova.
    - `distributionType` — `DIRECT_ENTITLEMENT` = **item de jogo** (o selo *IN-GAME ITEM*); `BADGE` =
      **badge da Twitch** (fotinha do chat). Badge aberta a todos entra marcada *Badge / plataforma*: o site
      separa pelo selo e o bot ignora. A pasta da imagem não decide mais — Onimusha Armament e Sorcerer Rogier
      são badges servidas da mesma pasta dos itens.
    - `requiredSubs` — drop que exige sub não se ganha assistindo: fica de fora.
  - **Memória** (`data/`, escrita **só pelo Actions**): `categorias_vigiadas.json` (onde procurar — a
    Twitch não deixa paginar a lista de categorias sem o token do navegador) e `campanhas_conhecidas.json`
    (drop de jogo já confirmado vale 24h mesmo que ninguém esteja ao vivo naquele jogo no momento).
  - **badges chegando:** [streamdatabase.com/events](https://www.streamdatabase.com/events) — a única
    coisa que **não** vem da Twitch, porque é sobre badge que ainda **vai** existir, e a GQL só
    responde sobre o que está ativo num canal ao vivo agora. Nunca gerou live: o bot ignora essa chave.
- **Checador** (`checker.py` + `twitch_gql.py`): roda no **GitHub Actions** a cada 10 min (~2 min por
  rodada, ~310 perguntas à Twitch), filtra e escreve `data/drops.json`.
  Antes de escrever ele obedece o [`jogos-fora.txt`](jogos-fora.txt) (veja abaixo).
- **Testes:** `python teste_checker.py` (offline, com respostas reais capturadas — o caso Minecraft, o
  Apex ALGS fechado, badges disfarçadas de item, drop de sub) e `python teste_checker.py --ao-vivo`.
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

## Jogos que eu nao quero ver

Abra o **[`jogos-fora.txt`](jogos-fora.txt)** aqui no GitHub, clique no lapis, escreva o nome do
jogo numa linha nova e salve. So isso, de qualquer PC ou do celular.

- Basta um pedaco do nome: `black desert` tira o *Black Desert Online* junto.
- Nao precisa acento, maiuscula nem pontuacao certa.
- Linha comecando com `#` e recado, o robo pula.

Salvou, o robo roda na hora (o workflow escuta esse arquivo) e em ~1 minuto o jogo sumiu do
radar, do `data/drops.json`, do site **miviye.com/games** e dos avisos do `alerta_drops.py`.
Mudou de ideia? Apague a linha e ele volta na proxima rodada.

O `counts.fora_da_lista` no JSON diz quantas campanhas a lista cortou na ultima passada.

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
