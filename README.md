# agenda-clinica

<!-- resumo: Site de clínica com agendamento online grátis e de código aberto (MIT): vários profissionais e locais, painel com login para bloquear agenda, cancelar e remarcar, API REST e servidor MCP para agentes; Python stdlib + SQLite, roda no k3s. -->

Site de clínica + agendamento online. Grátis, código aberto (MIT), sem dependências (só a biblioteca padrão do Python 3.12 e SQLite).
Nasceu de um pedido real: *duas profissionais, dois locais, painel com login para gerenciar horários, bloquear agenda, cancelar e remarcar consultas*.

| | |
|---|---|
| **No ar** | https://agenda-clinica.genesisinnovation.io (demo em `/c/demo`) |
| **Stack** | Python 3.12 stdlib, SQLite (WAL) em `DATA_DIR`, HTML sem JavaScript |
| **Rodar** | `DATA_DIR=./data DEMO=1 python3 app.py` e abra http://localhost:8080 |
| **Testar** | `python3 -m pytest -q tests` |
| **Imagem** | `docker build -t agenda-clinica . && docker run -p 8080:8080 -v agenda:/data agenda-clinica` |
| **Kubernetes** | um Deployment com 1 réplica, `DATA_DIR` num volume (PVC) e a imagem do `Dockerfile`; sem dependência externa |

## Como usar (do zero ao ar)

**Testar na sua máquina (2 minutos, sem instalar nada além do Python 3.12):**

    git clone https://github.com/thiagopatzdorf/agenda-clinica && cd agenda-clinica
    DATA_DIR=./data DEMO=1 python3 app.py        # abre em http://localhost:8080, com a clínica de demonstração em /c/demo

**Subir a sua clínica, sem a demonstração:**

1. Rode `docker build -t agenda-clinica . && docker run -p 8080:8080 -v agenda:/data -e BASE_URL=https://agenda.seudominio.com agenda-clinica`.
   O volume `/data` guarda o banco; sem ele, os dados somem ao reiniciar. Ponha um proxy com HTTPS na frente (o cookie de login é `Secure` fora do localhost).
2. Abra `/criar`, informe nome, e-mail e senha da clínica e o endereço do site (`/c/<endereço>`).
3. No `/painel`: cadastre os **locais**, a **equipe** (profissionais), os **serviços** e o **horário semanal** de cada profissional por local.
4. Compartilhe `/c/<endereço>`. O paciente agenda sem conta e recebe um código para ver, cancelar ou remarcar em `/m/<código>`.
5. Para um agente de IA operar a agenda, crie uma **chave de API** em `/painel/api` e use o servidor MCP (veja abaixo).

Backup: `python3 app.py backup <arquivo>`. Tirar uma página do índice de busca: `python3 app.py delistar <endereço>`.

## O que faz

- **Site da clínica** em `/c/<endereço>`: profissionais, serviços, locais, JSON-LD `MedicalClinic` (indexável).
- **Agendamento sem conta e sem JavaScript**: serviço → horário livre (próximos 14 dias, por profissional e local) → nome e telefone. O paciente recebe um **código**
  para ver, cancelar ou remarcar em `/m/<código>`.
- **Painel** em `/painel` (login por e-mail e senha, scrypt): agenda do dia, cancelar, remarcar, **bloquear agenda** (de um profissional ou da clínica toda, com opção de cancelar
  as consultas atingidas), locais, equipe, serviços, horário semanal por local (duas faixas por dia) e chaves de API.
- **Sem choque de horário**: a checagem e a gravação acontecem na mesma transação (`BEGIN IMMEDIATE`); há teste com 8 pedidos simultâneos para o mesmo horário.
- **Visual imersivo**: fotos de fundo do **Unsplash** e do **Pexels** (uso livre), **servidas do nosso domínio** (`/static/fundos/`, sem hotlink: nenhum terceiro vê o acesso do paciente), com crédito em cada página e em `/creditos`. Cada clínica ganha uma foto estável pelo endereço dela. O painel fica limpo, sem foto. Trocar ou somar foto = um `.jpg` em `static/fundos/`, a entrada em `static/creditos.json` e o nome em `POOL` (`paginas.py`); um teste falha se faltar o arquivo ou o crédito.
- **LGPD**: guarda só nome, telefone e e-mail opcional; consentimento explícito; nenhum dado clínico; sem rastreadores.

## Para agentes (API e MCP)

Cada operação é declarada **uma vez** em `ops.py`; REST, MCP, OpenAPI e `llms.txt` saem da mesma tabela (`tests/test_http.py` falha se divergirem).

- **MCP**: `POST /mcp` (Streamable HTTP, JSON-RPC 2.0, sem sessão). Sem chave: `clinica_info`, `horarios_livres`, `agendar`, `ver_consulta`, `cancelar_consulta`, `remarcar_consulta`.
  Com chave (`Authorization: Bearer ac_...`, criada no painel): também listar, cancelar, remarcar, bloquear, configurar.
- **REST**: `/api/v1/...`, esquema em `/openapi.json`. Erros: `{"erro":{"codigo":"horario_indisponivel","mensagem":"..."}}`.
- Guia humano em `/docs`, resumo para LLMs em `/llms.txt`.

```json
{"mcpServers": {"agenda-clinica": {"type": "http", "url": "https://agenda-clinica.genesisinnovation.io/mcp"}}}
```

## Limites conhecidos (declarados, não escondidos)

- **Não envia mensagens** (WhatsApp/e-mail). O painel dá o link `wa.me` do paciente; quem avisa é a clínica. Lembrete automático é a próxima fatia.
- **Um processo, um banco SQLite**: serve bem uma região; escalar para várias réplicas exige trocar o armazenamento (as funções de `nucleo.py` são o único ponto que toca SQL).
- **Backup**: cópia diária consistente (`VACUUM INTO`, 7 últimas) em `DATA_DIR/backups`. Cópia **fora do disco** ainda é responsabilidade de quem opera.
- Limite de taxa em memória, por processo (por IP, por conta no login e por clínica nos agendamentos anônimos). Sem recuperação de senha por e-mail (peça ao operador; o hash é scrypt).
- **Agendamento anônimo não verifica o telefone** (sem OTP nem captcha): dá para encher uma agenda com nomes falsos (teto de 20/h por IP e 60/h por clínica) ou ocupar o limite de 5 consultas futuras do telefone de outra pessoa. Verificação por código é a próxima fatia de segurança.
- **Cadastro aberto sem verificação de e-mail, e toda clínica nasce indexável** (decisão do dono: "indexa tudo"). O risco é alguém publicar página indexada com o nome de uma marca alheia ou spam sob o nosso domínio: o operador tira a página do índice com `python3 app.py delistar <endereço>` (e `listar` desfaz). Há teto de 100 clínicas novas por dia.
- Tetos: 30 profissionais, 20 locais, 60 serviços, 10 chaves por clínica; consulta de horários até 14 dias e 300 linhas por resposta (`truncado: true` = refine); lote MCP até 10 itens; 100 clínicas novas por dia.

## Nichos: uma engine, vários negócios (barbearia e o que vier)

O mesmo motor atende outros tipos de negócio com hora marcada. O que muda por nicho é **dado**, em `nichos.json`: vocabulário (barbeiro em vez de profissional, horário em vez de consulta), as fotos de fundo, a página de entrada e a demonstração. **Não existe código por nicho**, e um teste (`tests/test_tamanho.py`) falha se o nome de um nicho aparecer num `.py`.

- Hoje: `clinica` (página `/`) e `barbearia` (página `/barbearia`, demo em `/c/demo-barbearia`). Quem cria a conta escolhe o nicho na página de entrada.
- **Nicho novo** = um objeto em `nichos.json` com as mesmas chaves de `clinica` (o teste cobra todas) + 3 fotos em `static/fundos` (cheia, `-m`, `-b`) com crédito em `static/creditos.json`. Nenhuma linha de Python.
- **Catraca de tamanho:** `tamanho.json` guarda o teto de linhas do código e de bytes do JSON e o peso das fotos; o teto só desce (`tests/test_tamanho.py`).
- A política de privacidade e o painel do dono ainda usam o texto de clínica para todos os nichos (dívida declarada).

## Para devs: rodar no seu servidor, migrar e gerenciar

A página `/devs` do serviço resume isto. Código MIT, Python 3.12 e SQLite, nada externo.

- **Rodar:** `docker compose up -d` (arquivo `docker-compose.yml` aqui) ou `python3 app.py`. Os dados são um arquivo SQLite em `DATA_DIR`; `python3 app.py backup arquivo.db` copia com o serviço no ar.
- **Migrar de um servidor para outro:** no servidor de origem, `python3 app.py exportar <slug> [--com-pacientes] > clinica.json` (ou, pela API, `GET /api/v1/exportar?com_pacientes=true` com chave de leitura; ou no painel, "Agentes e API → Levar seus dados"). No destino: `AGENDA_EMAIL=... AGENDA_SENHA=... python3 app.py importar clinica.json`. O arquivo é versionado (`agenda-clinica/1`) e **nunca leva senha, chaves, sessões nem a instância do WhatsApp**; o login novo é o que você define ao importar, e o WhatsApp não é ligado. Com pacientes, o código de cada consulta vai junto e os links `/m/<código>` continuam valendo. Arquivo com defeito: nada é importado (desfaz tudo). Código de consulta que já existe no destino é pulado, nunca sobrescrito.
- **Apagar o que ficou no servidor antigo:** `python3 app.py apagar <slug> --confirmo` (sem volta: exporte antes). Dado de paciente é da clínica (LGPD); quem hospeda é operador.
- **Gerenciar por API ou MCP:** chaves por clínica no painel (leitura ou escrita); o mesmo contrato vale no nosso servidor e no seu (`/mcp`, `/openapi.json`).

## Conta de dev: uma conta, vários clientes

Para agência, integrador ou o amigo que "faz o sistema" da clínica. Cadastro aberto em `/dev/cadastro` (e-mail e senha; limite por endereço e por dia). A conta tem:

- **Clientes (CRUD):** criar (clínica, barbearia ou outro tipo de `nichos.json`), listar, definir o login do cliente (`dev_clinica_acesso`), exportar e apagar (com confirmação do slug; sem volta). Limite de 50 clientes por conta.
- **Suporte:** "Entrar como suporte" abre o painel do cliente por 8 h. O dev **vê nome e telefone dos pacientes dos próprios clientes** (decisão de produto: o dev dá o suporte) e a política de privacidade avisa o paciente.
- **Chave de dev (`ad_...`)** por API e MCP: as operações dev_* e todas as de chave, com `clinica=<slug do cliente>`. Nunca vale em cliente de outro dev (nem na demonstração).
- O painel é `/dev`; o cookie da conta de dev vale só em `/dev` e é separado do cookie do painel da clínica.
- **Entrar com Google e GitHub** (OAuth 2.0 com PKCE, sem biblioteca): `oauth.py`. O botão de cada provedor só aparece se o servidor tem `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` ou `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`. Endereço de retorno a cadastrar no provedor: `<BASE_URL>/entrar/google/retorno` e `<BASE_URL>/entrar/github/retorno`. **Só vale e-mail verificado pelo provedor** (no GitHub, o primário verificado); conta nova respeita o limite diário e conta existente com o mesmo e-mail verificado é ligada, nunca duplicada. Os testes rodam contra um provedor falso local.

## Protocolo aberto e personalização

- **Protocolo (`PROTOCOLO.md`, `schema/agenda-clinica-1.schema.json`, rotas `/protocolo`, `/protocolo.md`, `/schema/agenda-clinica-1.json`):** o contrato que um servidor precisa falar para ser compatível (API e MCP, escopos, erros, chaves de clínica e de dev, e o arquivo de intercâmbio `agenda-clinica/1`). Um teste confere que o esquema descreve **exatamente** o que o servidor exporta: campo novo no código sem o esquema derruba o teste.
- **Personalização por cliente** (conta de dev: `dev_clinica_personalizar` ou o painel `/dev`): `cor` de destaque e `rotulos` (os textos do site e da página do cliente final, só chaves de `nichos.json`). Regra medida, não gosto: cor com contraste 4,5:1 contra o branco do botão (WCAG AA), rótulo sem HTML nem aspas e até 80 caracteres. A cor vale no tema claro; o escuro mantém o tom padrão. A personalização viaja no arquivo de exportação.

## Lembrete por WhatsApp (Evolution) — leia o risco

Opcional e **desligado por padrão**. Cada agendamento pode gerar **1 confirmação e 1 lembrete** por WhatsApp, enviados pela instância do [Evolution API](https://github.com/EvolutionAPI/evolution-api) que **a própria clínica conectou** (o QR é lido no Evolution, não aqui).

> **RISCO: o Evolution usa o WhatsApp Web (não oficial).** O WhatsApp pode **banir o número** que manda mensagem em massa, para quem não o tem salvo ou para quem denuncia. Use um **número só da clínica**, nunca para divulgação ou spam. Para volume ou garantia, use a API oficial da Meta (este projeto não a implementa).

Como o desenho impede o uso como disparador de spam:
- **Não existe operação** (REST, MCP ou painel) que receba número ou texto livre. O lembrete só nasce como consequência de um agendamento real e vai para o telefone de quem agendou, com o texto fixo do sistema.
- Teto por clínica por dia (`WHATSAPP_TETO_DIA`, padrão 100), 3 s entre mensagens, 3 tentativas e instância desconectada não vira laço de erro.
- Toda mensagem leva o link `/m/<código>/sem-lembrete`: o paciente para de receber (por telefone, naquela clínica) com um clique. O GET só mostra a página; só o POST descadastra (pré-visualizador de link não descadastra ninguém).
- Para **ligar** é obrigatório `aceito_risco=true` (a API/MCP `whatsapp_configurar` recusa sem isso; o painel tem a caixa de ciência).
- "enviado" quer dizer **aceito pelo Evolution**, não "chegou no aparelho": o Evolution não expõe a entrega.

Configuração do servidor (o operador): `EVOLUTION_URL`, `EVOLUTION_KEY` (só no ambiente, nunca gravada nem devolvida) e `BASE_URL` (os links da mensagem precisam dele). Sem os três, a rotina nem sobe. Depois, a clínica liga em `/painel/whatsapp`, ou um agente com chave de escrita chama `whatsapp_configurar` (`whatsapp_status` e `lembretes_listar` mostram a situação).

## Código

`nucleo.py` regras e SQL · `ops.py` operações (REST+MCP+OpenAPI) · `paginas.py` HTML · `app.py` servidor, painel, MCP · `tests/` (nome do teste = a falha que ele impede).
Contribuições são bem-vindas: abra uma issue com o caso real.
