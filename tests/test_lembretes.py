"""Lembretes por WhatsApp (Evolution). Regra de ouro dos testes: NUNCA falar com WhatsApp real. O envio é trocado por um falso, e o contrato HTTP
do Evolution é conferido contra um servidor falso local. O nome de cada teste descreve a falha que ele impede."""
import datetime as dt
import http.server
import json
import threading

import lembretes as lem
import nucleo as n
import ops
import pytest
from conftest import proxima
from test_http import req  # cliente HTTP dos testes de rede

TEL = "(48) 99999-0000"
CHAVE_EVO = "chave-do-evolution-so-no-ambiente"


@pytest.fixture
def srv(tmp_path):
    import app as ap
    s, a = ap.servidor(tmp_path, 0, "http://t.test")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    ap.semear_demo(a.bd)
    yield s.server_address[1], a
    s.shutdown()
    s.server_close()


class EvolutionFalso:
    """Servidor local que imita as 2 rotas usadas do Evolution e guarda o que recebeu."""

    def __init__(self, estado="open", status_envio=201):
        self.pedidos, self.estado, self.status_envio = [], estado, status_envio
        dono = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _resp(self, status, corpo):
                b = json.dumps(corpo).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                dono.pedidos.append(("GET", self.path, self.headers.get("apikey"), None))
                self._resp(200, {"instance": {"instanceName": "x", "state": dono.estado}})

            def do_POST(self):
                corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                dono.pedidos.append(("POST", self.path, self.headers.get("apikey"), corpo))
                self._resp(dono.status_envio, {"key": {"id": "abc"}})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def parar(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def evo(monkeypatch):
    f = EvolutionFalso()
    monkeypatch.setenv("EVOLUTION_URL", f.url)
    monkeypatch.setenv("EVOLUTION_KEY", CHAVE_EVO)
    yield f
    f.parar()


@pytest.fixture
def enviados(monkeypatch):
    """Troca o envio real por um que só anota (instância, telefone, texto)."""
    feitos = []
    monkeypatch.setattr(lem, "ENVIAR", lambda inst, tel, txt: (feitos.append((inst, tel, txt)) or (True, "aceito (falso)")))
    monkeypatch.setattr(lem, "estado_instancia", lambda inst: "conectado")
    return feitos


def ligar(bd, clinica, confirmacao=False, horas=24, instancia="clinica-aurora"):
    n.salvar_whatsapp(bd, clinica["row"], True, instancia, horas, confirmacao)
    clinica["row"] = bd.um("select * from clinicas where id=?", (clinica["id"],))
    return clinica["row"]


def marcar(bd, clinica, data, hora="09:00", tel=TEL, prof=None):
    return n.agendar(bd, clinica["row"], clinica["retorno"], prof or clinica["ana"], data, hora, "Maria Souza", tel, "", consentimento=True)


def lembretes(bd, aid=None):
    return [dict(r) for r in bd.ler("select * from lembretes where (? is null or agendamento_id=?) order by id", (aid, aid))]


def vencer_tudo(bd):
    with bd.escrita() as con:
        con.execute("update lembretes set enviar_em='2000-01-01T00:00:00Z' where status='pendente'")


# ---------------------------------------------------------------- quando nasce lembrete

def test_whatsapp_desligado_nao_cria_lembrete_nenhum(bd, clinica):
    marcar(bd, clinica, proxima(1, 5))
    assert lembretes(bd) == []


def test_ligado_agenda_o_lembrete_na_antecedencia_certa_e_confirmacao_so_se_pedida(bd, clinica):
    ligar(bd, clinica, confirmacao=False, horas=24)
    seg = proxima(1, 5)
    ag = marcar(bd, clinica, seg, "09:00")
    [lem1] = lembretes(bd, ag["id"])
    inicio = n._inicio_utc("America/Sao_Paulo", dt.date.fromisoformat(seg), 9 * 60)
    assert lem1["tipo"] == "lembrete" and lem1["enviar_em"] == (inicio - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ligar(bd, clinica, confirmacao=True)
    ag2 = marcar(bd, clinica, seg, "10:00", tel="(48) 98888-0000")
    assert [x["tipo"] for x in lembretes(bd, ag2["id"])] == ["confirmacao", "lembrete"]


def test_consulta_em_cima_da_hora_nao_gera_lembrete_inutil(bd, clinica):
    c = ligar(bd, clinica)
    ag = marcar(bd, clinica, proxima(1, 5))
    agora = dt.datetime.now(dt.timezone.utc)
    for horas_ate, esperado in ((1, 0), (5, 1)):  # faltando 1 h não adianta; faltando 5 h lembra já (em ~1 min)
        alvo = (agora + dt.timedelta(hours=horas_ate)).astimezone(dt.timezone(dt.timedelta(hours=-3)))
        with bd.escrita() as con:
            n._programar(con, c, ag["id"], alvo.date(), alvo.hour * 60 + alvo.minute, "48999990000")
        assert len([x for x in lembretes(bd, ag["id"]) if x["status"] == "pendente"]) == esperado


# ---------------------------------------------------------------- cancelar, remarcar, bloquear

def test_cancelar_e_bloquear_a_agenda_cancelam_os_lembretes_pendentes(bd, clinica):
    ligar(bd, clinica)
    seg = proxima(1, 5)
    a1, a2 = marcar(bd, clinica, seg, "09:00"), marcar(bd, clinica, seg, "10:00", tel="(48) 98888-0000")
    n.cancelar(bd, bd.um("select * from agendamentos where id=?", (a1["id"],)), "paciente")
    n.bloquear(bd, clinica["row"], f"{seg}T08:00", f"{seg}T18:00", clinica["ana"], "congresso", cancelar_conflitos=True)
    assert {x["status"] for x in lembretes(bd)} == {"cancelado"} and len(lembretes(bd, a2["id"])) == 1


def test_remarcar_reprograma_o_lembrete_e_nao_repete_o_que_ja_foi_enviado(bd, clinica, enviados):
    ligar(bd, clinica)
    seg, qua = proxima(1, 5), proxima(3, 6)
    ag = marcar(bd, clinica, seg, "09:00")
    n.remarcar(bd, clinica["row"], bd.um("select * from agendamentos where id=?", (ag["id"],)), qua, "10:00", None, "paciente")
    pend = [x for x in lembretes(bd, ag["id"]) if x["status"] == "pendente"]
    assert len(pend) == 1 and pend[0]["enviar_em"].startswith((dt.date.fromisoformat(qua) - dt.timedelta(days=1)).isoformat())
    vencer_tudo(bd)
    assert lem.rodar_uma_vez(bd, "https://x.test", pausa_s=0)["enviados"] == 1
    n.remarcar(bd, clinica["row"], bd.um("select * from agendamentos where id=?", (ag["id"],)), seg, "10:00", None, "paciente")
    assert [x for x in lembretes(bd, ag["id"]) if x["status"] == "pendente"] == [], "já foi lembrado: remarcar não manda de novo"


# ---------------------------------------------------------------- envio (freios)

def test_envia_so_para_o_telefone_de_quem_agendou_com_link_de_sair_e_so_uma_vez(bd, clinica, enviados):
    ligar(bd, clinica, confirmacao=True)
    ag = marcar(bd, clinica, proxima(1, 5), "09:00", tel="(48) 97777-1234")
    vencer_tudo(bd)
    assert lem.rodar_uma_vez(bd, "https://agenda.test", pausa_s=0)["enviados"] == 2
    assert {tel for _, tel, _ in enviados} == {"48977771234"}
    texto = enviados[-1][2]
    assert f"https://agenda.test/m/{ag['codigo']}/sem-lembrete" in texto and "Maria Souza" in texto
    assert lem.rodar_uma_vez(bd, "https://agenda.test", pausa_s=0)["enviados"] == 0, "não pode reenviar o que já foi"


def test_paciente_que_pediu_para_sair_nunca_mais_recebe_nem_nas_proximas_consultas(bd, clinica, enviados):
    ligar(bd, clinica)
    a1 = marcar(bd, clinica, proxima(1, 5), "09:00")
    lem.nao_quero(bd, a1["codigo"])
    marcar(bd, clinica, proxima(1, 6), "10:00")  # mesma pessoa, consulta nova
    vencer_tudo(bd)
    assert lem.rodar_uma_vez(bd, "https://x.test", pausa_s=0)["enviados"] == 0 and enviados == []


def test_teto_diario_por_clinica_segura_o_excesso_em_vez_de_arriscar_o_numero(bd, clinica, enviados, monkeypatch):
    monkeypatch.setenv("WHATSAPP_TETO_DIA", "2")
    ligar(bd, clinica)
    for h in ("09:00", "09:30", "10:00"):
        marcar(bd, clinica, proxima(1, 5), h, tel=f"(48) 9{h[:2]}{h[3:]}-0000")
    vencer_tudo(bd)
    c = lem.rodar_uma_vez(bd, "https://x.test", pausa_s=0)
    assert c["enviados"] == 2 and c["adiados"] == 1 and len(enviados) == 2


def test_instancia_desconectada_tenta_3_vezes_e_desiste_sem_laco_de_erro(bd, clinica, monkeypatch):
    ligar(bd, clinica)
    marcar(bd, clinica, proxima(1, 5))
    monkeypatch.setattr(lem, "estado_instancia", lambda i: "desconectado")
    monkeypatch.setattr(lem, "ENVIAR", lambda *a: pytest.fail("não pode mandar com a instância desconectada"))
    for _ in range(5):
        vencer_tudo(bd)
        lem.rodar_uma_vez(bd, "https://x.test", pausa_s=0)
    [l1] = lembretes(bd)
    assert l1["status"] == "falhou" and l1["tentativas"] == lem.MAX_TENTATIVAS and "desconectado" in l1["detalhe"]


def test_desligar_o_whatsapp_cancela_o_que_estava_na_fila(bd, clinica, enviados):
    ligar(bd, clinica)
    marcar(bd, clinica, proxima(1, 5))
    n.salvar_whatsapp(bd, clinica["row"], False, None, None, None)
    vencer_tudo(bd)
    assert lem.rodar_uma_vez(bd, "https://x.test", pausa_s=0)["enviados"] == 0 and {x["status"] for x in lembretes(bd)} == {"cancelado"}


# ---------------------------------------------------------------- contrato com o Evolution

def test_chamada_ao_evolution_tem_o_formato_certo_e_a_chave_vai_so_no_cabecalho(bd, evo):
    assert lem.estado_instancia("minha") == "conectado"
    assert lem.enviar("minha", "(48) 99999-0000", "oi") == (True, "aceito pelo Evolution")
    (g, p) = evo.pedidos
    assert g[:3] == ("GET", "/instance/connectionState/minha", CHAVE_EVO)
    assert p == ("POST", "/message/sendText/minha", CHAVE_EVO, {"number": "5548999990000", "text": "oi"})


def test_evolution_fora_do_ar_ou_recusando_nao_derruba_nem_finge_que_enviou(bd, evo, monkeypatch):
    evo.estado = "close"
    assert lem.estado_instancia("minha") == "desconectado"
    evo.status_envio = 400
    assert lem.enviar("minha", "48999990000", "oi")[0] is False
    monkeypatch.setenv("EVOLUTION_URL", "http://127.0.0.1:9")  # nada escutando
    assert lem.estado_instancia("minha") == "indisponivel" and lem.enviar("minha", "48999990000", "oi")[0] is False


# ---------------------------------------------------------------- API, MCP e painel

def test_nenhuma_operacao_aceita_numero_ou_texto_livre_porque_isso_seria_disparador_de_spam():
    proibidos = {"telefone", "numero", "numeros", "para", "texto", "mensagem", "text", "message", "destinatario"}
    for nome in ("whatsapp_status", "whatsapp_configurar", "lembretes_listar"):
        assert not proibidos & {p["nome"] for p in ops.OPS[nome]["params"]}, nome
    assert not [o for o in ops.OPS if "enviar" in o or "mensagem" in o]


def test_ligar_exige_evolution_no_servidor_e_a_ciencia_do_risco(bd, clinica, monkeypatch):
    monkeypatch.delenv("EVOLUTION_URL", raising=False)
    monkeypatch.delenv("EVOLUTION_KEY", raising=False)
    with pytest.raises(n.Erro) as e1:
        lem.configurar(bd, clinica["row"], True, "minha", 24, False, True)
    assert e1.value.codigo == "whatsapp_indisponivel"
    monkeypatch.setenv("EVOLUTION_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLUTION_KEY", CHAVE_EVO)
    with pytest.raises(n.Erro) as e2:
        lem.configurar(bd, clinica["row"], True, "minha", 24, False, False)
    assert e2.value.codigo == "risco_nao_aceito" and "BANIR" in e2.value.mensagem
    assert lem.configurar(bd, clinica["row"], True, "minha", 24, False, True)["ativo"] is True


@pytest.mark.parametrize("instancia", ["", "a b", "x" * 41, "ab", "../etc"])
def test_nome_de_instancia_invalido_e_recusado(bd, clinica, instancia):
    with pytest.raises(n.Erro):
        n.salvar_whatsapp(bd, clinica["row"], True, instancia, 24, False)


def test_status_e_openapi_nunca_expoem_a_chave_do_evolution(srv, evo):
    porta, a = srv
    chave = n.criar_chave(a.bd, n.clinica_por_slug(a.bd, "demo")["id"], "t", "escrita")["chave"]
    h = {"Authorization": f"Bearer {chave}"}
    st, corpo, _ = req(porta, "PATCH", "/api/v1/whatsapp", {"ativo": True, "instancia": "demo-wa", "aceito_risco": True}, cab=h)
    assert st == 200 and corpo["ativo"] is True and "BANIR" in corpo["aviso"]
    _, status, _ = req(porta, "GET", "/api/v1/whatsapp", cab=h)
    _, openapi, _ = req(porta, "GET", "/openapi.json")
    _, llms, _ = req(porta, "GET", "/llms.txt")
    assert CHAVE_EVO not in json.dumps(status) + json.dumps(openapi) + llms
    assert req(porta, "GET", "/api/v1/whatsapp")[0] == 401, "sem chave não vê nem a configuração"


def test_painel_mostra_o_aviso_de_risco_e_recusa_ligar_sem_marcar_a_ciencia(srv, evo):
    porta, a = srv
    c = n.clinica_por_slug(a.bd, "demo")
    n.salvar_clinica(a.bd, c, {})
    with a.bd.escrita() as con:
        con.execute("insert into usuarios(clinica_id,email,senha,criado) values(?,?,?,?)", (c["id"], "wa@t.test", n.hash_senha("senha-bem-longa"), "x"))
    st, _, r = req(porta, "POST", "/entrar", form={"email": "wa@t.test", "senha": "senha-bem-longa"})
    cookie = r.getheader("Set-Cookie").split(";")[0]
    _, html, _ = req(porta, "GET", "/painel/whatsapp", cab={"Cookie": cookie})
    assert "BANIR" in html and "Evolution" in html and "não há como mandar mensagem a um número" in html
    tok = cookie.split("=", 1)[1]
    st, _, r = req(porta, "POST", "/painel/acao", cab={"Cookie": cookie},
                   form={"csrf": n.csrf_de(tok), "acao": "whatsapp", "ativo": "1", "instancia": "demo-wa", "volta": "/painel/whatsapp"})
    assert st == 303 and "erro=" in r.getheader("Location") and not a.bd.um("select whatsapp_ativo from clinicas where id=?", (c["id"],))[0]


def test_link_de_sair_so_descadastra_no_post_porque_pre_visualizador_de_link_faz_get(srv, evo):
    porta, a = srv
    c = n.clinica_por_slug(a.bd, "demo")
    n.salvar_whatsapp(a.bd, c, True, "demo-wa", 24, False)
    c = n.clinica_por_slug(a.bd, "demo")
    info = n.info_publica(a.bd, c)
    ag = n.agendar(a.bd, c, info["servicos"][1]["id"], info["profissionais"][1]["id"], proxima(1, 6), "08:00", "Joana", "48911112222", "", consentimento=True)
    st, html, _ = req(porta, "GET", f"/m/{ag['codigo']}/sem-lembrete")
    assert st == 200 and "Parar de receber" in html and a.bd.um("select count(*) from sem_lembrete")[0] == 0
    st, html, _ = req(porta, "POST", f"/m/{ag['codigo']}/sem-lembrete", form={})
    assert st == 200 and "Pronto" in html and a.bd.um("select count(*) from sem_lembrete")[0] == 1
    assert {x["status"] for x in lembretes(a.bd, ag["id"])} == {"cancelado"}


def test_pagina_de_agendado_so_promete_lembrete_quando_o_whatsapp_esta_ligado(bd, clinica):
    import paginas as pg
    seg = proxima(1, 5)
    ag = marcar(bd, clinica, seg, "09:00")
    desligado = pg.agendado(n.info_publica(bd, clinica["row"]), ag, "https://x.test")
    assert "não envia mensagem automática" in desligado and "lembrete por WhatsApp" not in desligado
    c = ligar(bd, clinica)
    ligado = pg.agendado(n.info_publica(bd, c), ag, "https://x.test")
    assert "receberá um lembrete por WhatsApp" in ligado and "não envia mensagem automática" not in ligado
