"""Regras da agenda. O nome de cada teste descreve a falha que ele impede."""
import threading

import pytest

import nucleo as n
from conftest import proxima

PACIENTE = dict(nome="Maria Souza", telefone="(48) 99999-0000", email="", consentimento=True)


def agendar(bd, c, data, hora, prof=None, serv=None, **kw):
    dados = {**PACIENTE, **kw}
    return n.agendar(bd, c["row"], serv or c["retorno"], prof or c["ana"], data, hora, dados["nome"], dados["telefone"],
                     dados["email"], consentimento=dados["consentimento"])


def horas(bd, c, data, prof, serv=None, local=None):
    return [h["hora"] for h in n.horarios_livres(bd, c["row"], serv or c["retorno"], prof, data, None, local)]


def test_dois_pedidos_simultaneos_para_o_mesmo_horario_so_um_passa(bd, clinica):
    seg = proxima(1)
    resultados = []

    def tentar(i):
        try:
            agendar(bd, clinica, seg, "09:00", telefone=f"4899999000{i}")
            resultados.append("ok")
        except n.Erro as e:
            resultados.append(e.codigo)

    ts = [threading.Thread(target=tentar, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert resultados.count("ok") == 1 and resultados.count("horario_indisponivel") == 7


def test_horario_agendado_some_da_lista_e_cancelar_devolve(bd, clinica):
    seg = proxima(1)
    assert "09:00" in horas(bd, clinica, seg, clinica["ana"])
    ag = agendar(bd, clinica, seg, "09:00")
    assert "09:00" not in horas(bd, clinica, seg, clinica["ana"])
    n.cancelar(bd, n.agendamento_da_clinica(bd, clinica["row"], ag["id"]), "clinica")
    assert "09:00" in horas(bd, clinica, seg, clinica["ana"])


def test_consulta_de_50_min_nao_deixa_horario_que_invade_a_proxima(bd, clinica):
    seg = proxima(1)
    agendar(bd, clinica, seg, "09:00", serv=clinica["consulta"])  # 09:00-09:50
    h = horas(bd, clinica, seg, clinica["ana"], clinica["consulta"])
    assert "09:30" not in h and "10:00" in h  # 09:30 invadiria os 09:00-09:50


def test_profissional_so_atende_nos_dias_e_no_local_da_agenda_semanal(bd, clinica):
    ter, seg = proxima(2), proxima(1)
    assert horas(bd, clinica, ter, clinica["ana"])[0] == "14:00"
    ocup = n.horarios_livres(bd, clinica["row"], clinica["retorno"], clinica["ana"], ter)
    assert {h["local_id"] for h in ocup} == {clinica["praia"]}
    assert {h["local_id"] for h in n.horarios_livres(bd, clinica["row"], clinica["retorno"], clinica["ana"], seg)} == {clinica["centro"]}
    assert horas(bd, clinica, proxima(5), clinica["ana"]) == []  # sexta: Ana não atende


def test_horario_fora_da_agenda_semanal_e_recusado_mesmo_sem_passar_pela_lista(bd, clinica):
    with pytest.raises(n.Erro) as e:
        agendar(bd, clinica, proxima(1), "20:00")
    assert e.value.codigo == "horario_indisponivel"


def test_bloqueio_remove_horarios_e_recusa_quando_ha_consulta_confirmada(bd, clinica):
    seg = proxima(1)
    agendar(bd, clinica, seg, "10:00")
    with pytest.raises(n.Erro) as e:
        n.bloquear(bd, clinica["row"], f"{seg}T09:00", f"{seg}T12:00", clinica["ana"], "congresso")
    assert e.value.codigo == "conflito_com_consultas"
    assert horas(bd, clinica, seg, clinica["ana"])  # nada foi bloqueado pela metade


def test_bloqueio_com_cancelar_conflitos_cancela_a_consulta_e_zera_o_dia(bd, clinica):
    seg = proxima(1)
    ag = agendar(bd, clinica, seg, "10:00")
    b = n.bloquear(bd, clinica["row"], f"{seg}T00:00", f"{seg}T23:59", clinica["ana"], "folga", cancelar_conflitos=True)
    assert [x["id"] for x in b["consultas_canceladas"]] == [ag["id"]]
    assert horas(bd, clinica, seg, clinica["ana"]) == []
    assert horas(bd, clinica, seg, clinica["bia"])  # só a Ana foi bloqueada
    n.remover_bloqueio(bd, clinica["row"], b["id"])
    assert horas(bd, clinica, seg, clinica["ana"])


def test_bloqueio_da_clinica_toda_vale_para_todos_e_atravessa_dias(bd, clinica):
    seg, ter = proxima(1), proxima(2)
    n.bloquear(bd, clinica["row"], f"{seg}T00:00", f"{ter}T23:59", None, "feriado")
    assert horas(bd, clinica, seg, clinica["ana"]) == [] and horas(bd, clinica, seg, clinica["bia"]) == []
    assert horas(bd, clinica, ter, clinica["ana"]) == []


def test_remarcar_para_meia_hora_depois_nao_conflita_com_o_proprio_horario(bd, clinica):
    seg = proxima(1)
    ag = agendar(bd, clinica, seg, "09:00", serv=clinica["consulta"])  # 09:00-09:50: 09:30 só é livre se ignorar a si mesma
    r = n.remarcar(bd, clinica["row"], n.agendamento_da_clinica(bd, clinica["row"], ag["id"]), seg, "09:30", None, "clinica")
    assert r["hora"] == "09:30" and r["fim"] == "10:20"
    assert "09:00" in horas(bd, clinica, seg, clinica["ana"])


def test_remarcar_para_horario_ocupado_e_recusado_e_o_original_continua(bd, clinica):
    seg = proxima(1)
    a1, a2 = agendar(bd, clinica, seg, "09:00"), agendar(bd, clinica, seg, "10:00", telefone="48988887777")
    with pytest.raises(n.Erro) as e:
        n.remarcar(bd, clinica["row"], n.agendamento_da_clinica(bd, clinica["row"], a1["id"]), seg, "10:00", None, "clinica")
    assert e.value.codigo == "horario_indisponivel"
    assert n.agendamento_da_clinica(bd, clinica["row"], a1["id"])["inicio"] == 540 and a2["status"] == "confirmado"


def test_remarcar_para_outro_profissional_muda_o_local_junto(bd, clinica):
    ter = proxima(2)
    ag = agendar(bd, clinica, ter, "14:00")  # Ana na Praia
    r = n.remarcar(bd, clinica["row"], n.agendamento_da_clinica(bd, clinica["row"], ag["id"]), proxima(1), "08:00", clinica["bia"], "clinica")
    assert r["profissional"] == "Bia" and r["local"] == "Centro"


def test_agendamento_cancelado_nao_pode_ser_cancelado_nem_remarcado_de_novo(bd, clinica):
    seg = proxima(1)
    ag = agendar(bd, clinica, seg, "09:00")
    row = n.agendamento_da_clinica(bd, clinica["row"], ag["id"])
    n.cancelar(bd, row, "paciente")
    row = n.agendamento_da_clinica(bd, clinica["row"], ag["id"])
    with pytest.raises(n.Erro):
        n.cancelar(bd, row, "paciente")
    with pytest.raises(n.Erro):
        n.remarcar(bd, clinica["row"], row, seg, "10:00", None, "paciente")


def test_sem_consentimento_nao_agenda_e_nada_e_gravado(bd, clinica):
    with pytest.raises(n.Erro) as e:
        agendar(bd, clinica, proxima(1), "09:00", consentimento=False)
    assert e.value.codigo == "consentimento"
    assert bd.um("select count(*) from agendamentos")[0] == 0


def test_mesmo_telefone_nao_enche_a_agenda_acima_do_limite(bd, clinica):
    seg = proxima(1)
    for i in range(n.LIMITES["futuros_por_telefone"]):
        agendar(bd, clinica, seg, f"{9 + i // 2:02d}:{'00' if i % 2 == 0 else '30'}", serv=clinica["retorno"])
    with pytest.raises(n.Erro) as e:
        agendar(bd, clinica, seg, "11:30")
    assert e.value.codigo == "limite_paciente"


def test_antecedencia_minima_esconde_horarios_proximos(bd, clinica):
    n.salvar_clinica(bd, clinica["row"], {"antecedencia_min": 10080})  # 7 dias
    row = bd.um("select * from clinicas where id=?", (clinica["id"],))
    assert n.horarios_livres(bd, row, clinica["retorno"], clinica["bia"], proxima(1, 1), None) == []


def test_janelas_sobrepostas_no_mesmo_dia_sao_recusadas_e_a_agenda_antiga_fica(bd, clinica):
    antes = n.disponibilidade_de(bd, clinica["ana"])
    with pytest.raises(n.Erro) as e:
        n.definir_disponibilidade(bd, clinica["id"], clinica["ana"], [{"dia": 1, "inicio": "09:00", "fim": "12:00", "local_id": clinica["centro"]},
                                                                     {"dia": 1, "inicio": "11:00", "fim": "13:00", "local_id": clinica["praia"]}])
    assert e.value.codigo == "janelas_sobrepostas" and n.disponibilidade_de(bd, clinica["ana"]) == antes


def test_local_de_outra_clinica_nao_entra_na_disponibilidade(bd, clinica):
    outra = n.criar_clinica(bd, "Outra", "x@outra.test", "senha-bem-longa", "outra")
    local_alheio = n.salvar_local(bd, outra["id"], {"nome": "Alheio"})
    with pytest.raises(n.Erro) as e:
        n.definir_disponibilidade(bd, clinica["id"], clinica["ana"], [{"dia": 1, "inicio": "09:00", "fim": "10:00", "local_id": local_alheio}])
    assert e.value.codigo == "local_nao_encontrado"


def test_servico_de_outra_clinica_nao_agenda(bd, clinica):
    outra = n.criar_clinica(bd, "Outra", "x@outra.test", "senha-bem-longa", "outra")
    serv = n.salvar_servico(bd, outra["id"], {"nome": "X", "duracao_min": 30})
    with pytest.raises(n.Erro):
        n.agendar(bd, clinica["row"], serv, clinica["ana"], proxima(1), "09:00", "Maria", "48999990000", consentimento=True)


def test_login_nao_revela_se_o_email_existe_e_sessao_expira_no_logout(bd, clinica):
    for email, senha in (("dona@aurora.test", "errada-errada"), ("ninguem@x.test", "qualquer-coisa-1")):
        with pytest.raises(n.Erro) as e:
            n.entrar(bd, email, senha)
        assert (e.value.status, e.value.codigo) == (401, "credenciais")
    tok = n.entrar(bd, "dona@aurora.test", "senha-bem-longa")
    assert n.clinica_da_sessao(bd, tok)["slug"] == "aurora"
    n.sair(bd, tok)
    assert n.clinica_da_sessao(bd, tok) is None


def test_chave_de_api_so_aparece_uma_vez_e_revogada_para_de_valer(bd, clinica):
    k = n.criar_chave(bd, clinica["id"], "agente", "escrita")
    assert n.autenticar_chave(bd, k["chave"])[1] == "escrita"
    assert k["chave"] not in str([dict(r) for r in bd.ler("select * from chaves")])  # só o hash fica no banco
    n.revogar_chave(bd, clinica["id"], bd.um("select id from chaves")["id"])
    assert n.autenticar_chave(bd, k["chave"]) is None


def test_slug_reservado_e_email_repetido_sao_recusados(bd, clinica):
    with pytest.raises(n.Erro) as e:
        n.criar_clinica(bd, "Painel", "a@b.test", "senha-bem-longa", "painel")
    assert e.value.codigo == "slug_invalido"
    with pytest.raises(n.Erro) as e:
        n.criar_clinica(bd, "Outra", "dona@aurora.test", "senha-bem-longa")
    assert e.value.codigo == "email_em_uso"
