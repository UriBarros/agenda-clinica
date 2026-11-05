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

## O que faz

- **Site da clínica** em `/c/<endereço>`: profissionais, serviços, locais, JSON-LD `MedicalClinic` (indexável).
- **Agendamento sem conta e sem JavaScript**: serviço → horário livre (próximos 14 dias, por profissional e local) → nome e telefone. O paciente recebe um **código**
  para ver, cancelar ou remarcar em `/m/<código>`.
- **Painel** em `/painel` (login por e-mail e senha, scrypt): agenda do dia, cancelar, remarcar, **bloquear agenda** (de um profissional ou da clínica toda, com opção de cancelar
  as consultas atingidas), locais, equipe, serviços, horário semanal por local (duas faixas por dia) e chaves de API.
- **Sem choque de horário**: a checagem e a gravação acontecem na mesma transação (`BEGIN IMMEDIATE`); há teste com 8 pedidos simultâneos para o mesmo horário.
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

## Código

`nucleo.py` regras e SQL · `ops.py` operações (REST+MCP+OpenAPI) · `paginas.py` HTML · `app.py` servidor, painel, MCP · `tests/` (nome do teste = a falha que ele impede).
Contribuições são bem-vindas: abra uma issue com o caso real.
