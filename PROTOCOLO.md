# Protocolo agenda-clinica

<!-- resumo: Contrato aberto do agenda-clinica (MIT): o que um servidor precisa falar para ser compatível: API REST e MCP, chaves de clínica e de dev, e o arquivo de intercâmbio agenda-clinica/1 para migrar de um servidor para outro. -->

Este documento é o contrato, não a implementação: qualquer servidor que fale isto é compatível com os agentes, as chaves e os arquivos de quem usa o nosso, e dá para sair de um para o outro. Licença MIT; a implementação de referência é este repositório (Python 3.12 e SQLite, sem dependência externa).

## 1. As três peças

| peça | onde está | quem manda |
|---|---|---|
| **API e MCP** | `/api/v1/...` e `/mcp`, descritas em `/openapi.json` | `ops.py` (uma tabela gera REST, MCP, OpenAPI e `llms.txt`) |
| **Arquivo de intercâmbio** | `agenda-clinica/1`, esquema em `/schema/agenda-clinica-1.json` | `migracao.py` e o esquema em `schema/` |
| **Chaves** | `Authorization: Bearer ...` | `ac_...` (uma clínica; leitura ou escrita) e `ad_...` (uma conta de dev; escreve em cada cliente dela) |

## 2. API e MCP

- A fonte da verdade é o **OpenAPI** servido por cada servidor. Um cliente deve ler `/openapi.json` em vez de supor operações.
- REST e MCP expõem **as mesmas operações** (um teste do repositório falha se uma sair de algum deles). No MCP cada operação é uma ferramenta (JSON-RPC 2.0 sobre `POST /mcp`, resposta JSON, sem sessão).
- **Escopos:** público (ver clínica e horários, agendar, gerir a própria consulta pelo código), `leitura`, `escrita` e `dev`. Operação acima do escopo da chave: 403 `escopo_insuficiente`; sem chave: 401 `chave_obrigatoria`.
- **Chave de dev:** age em cada cliente da conta passando `clinica=<slug>`; nunca em cliente de outra conta (403 `outra_clinica`).
- **Erro:** `{"erro": {"codigo": "...", "mensagem": "..."}}` com o status HTTP; no MCP, `isError` com o mesmo código. Códigos são estáveis: mensagem é para gente, código é para máquina.
- **Pacientes:** nome e telefone só aparecem para chave de leitura ou mais. Sem chave, nunca.

## 3. Arquivo de intercâmbio `agenda-clinica/1`

JSON UTF-8. O esquema (`schema/agenda-clinica-1.schema.json`) é normativo. Resumo:

- `formato`: sempre `"agenda-clinica/1"`. Um importador **deve recusar** qualquer outro valor.
- `clinica`, `locais`, `profissionais` (com `janelas` semanais), `servicos`, `bloqueios` e, opcionalmente, `personalizar` (`cor` e `rotulos`).
- `ref`: inteiro local ao arquivo que liga profissional, local e serviço; **não** é o id do banco e muda ao importar.
- `agendamentos` só existe com `com_pacientes: true` e traz o código de cada consulta, para os links `/m/<código>` continuarem valendo no servidor novo.
- **Nunca** entram no arquivo: senha, chaves de API, sessões, a instância do WhatsApp e a fila de lembretes. Quem importa define o login novo.
- Importar é **tudo ou nada**: arquivo com defeito não deixa clínica pela metade. Código de consulta que já existe no destino é pulado, nunca sobrescrito.

### Compatibilidade

- Campo novo **opcional** não muda a versão: leitor da versão 1 ignora o que não conhece (o esquema fechado vale para escritores).
- Mudança que quebra leitor antigo (campo removido, significado trocado, campo novo obrigatório) vira `agenda-clinica/2`, e o servidor passa a ler os dois.

## 4. O que cada servidor precisa

1. Servir `/openapi.json` e `/mcp` com as operações da seção 2.
2. Exportar e importar `agenda-clinica/1` (o repositório tem o comando `app.py exportar|importar|apagar`).
3. Não guardar nem devolver segredo de volta: chave só aparece na criação.
4. Dado de paciente é da clínica (LGPD): quem hospeda é operador. O arquivo com pacientes é dado pessoal e deve ser tratado como tal.

## 5. Mudar este documento

Mudança de protocolo entra por PR com o teste que a cobra (`tests/test_protocolo.py` confere que o esquema descreve exatamente o que o servidor exporta). Se o código e este texto divergirem, vale o esquema, depois o código.
