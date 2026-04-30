"""core.py — Lógica de negócio do Bolão Survivor (PostgreSQL)"""

import csv, os, json, re, hashlib
from collections import defaultdict
from datetime import datetime

from backend.db import (
    get_db,
    db_get_config, db_set_config,
    db_get_usuarios, db_save_usuario,
    db_get_grupos, db_save_grupo, db_save_grupos,
    db_get_funis, db_save_funis,
    db_get_apostas, db_save_apostas,
    db_get_resultados, db_save_resultado,
    db_get_saldo, db_get_creditos_usuario, db_add_credito,
    db_save_jogos, db_get_jogos,
)

ARQ_JOGOS    = os.environ.get("JOGOS_CSV", "jogos.csv")
LIMITE_GRUPO = 10
SENHA_ADMIN  = os.environ.get("SENHA_ADMIN", "admin123")


def carregar_json(chave: str, padrao=None):
    with get_db() as db:
        cfg = db_get_config(db)
    return cfg.get(chave, padrao if padrao is not None else {})


def salvar_json(chave: str, dados):
    with get_db() as db:
        db_set_config(db, {chave: dados})


def garantir_pasta_dados():
    pass


def carregar_config() -> dict:
    with get_db() as db:
        return db_get_config(db)


def salvar_config(cfg: dict):
    with get_db() as db:
        db_set_config(db, cfg)


def config_definida() -> bool:
    return "rodada_inicial" in carregar_config()


def rodada_inicial() -> int:
    return carregar_config().get("rodada_inicial", 1)


def rodada_ativa() -> int:
    return carregar_config().get("rodada_ativa", 0)


def prazo_apostas() -> str:
    return carregar_config().get("prazo_apostas", "")


def rodada_atual() -> int:
    cfg     = carregar_config()
    r_ativa = cfg.get("rodada_ativa", 0)
    if r_ativa:
        return r_ativa
    r_inicial = cfg.get("rodada_inicial", 1)
    total     = cfg.get("total_rodadas", 38)
    with get_db() as db:
        resultados = db_get_resultados(db)
    for r in range(r_inicial, total + 1):
        if str(r) not in resultados:
            return r
    return total


def rodada_aberta_para_apostas() -> int:
    return rodada_atual()


def prazo_expirado() -> bool:
    prazo = prazo_apostas()
    if not prazo:
        return False
    try:
        return datetime.now() > datetime.fromisoformat(prazo)
    except ValueError:
        return False


def jogos_confirmados_da_rodada() -> list:
    return carregar_config().get("jogos_confirmados", [])


def rodada_aberta_e_valida() -> bool:
    cfg = carregar_config()
    return (
        bool(cfg.get("rodada_ativa", 0)) and
        bool(cfg.get("jogos_confirmados")) and
        not prazo_expirado()
    )


def carregar_jogos(caminho_csv: str) -> dict:
    if not os.path.exists(caminho_csv):
        raise FileNotFoundError(f"Arquivo '{caminho_csv}' nao encontrado.")
    rodadas: dict = defaultdict(list)
    with open(caminho_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols   = {"rodada", "time_casa", "time_visitante"}
        if not cols.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV precisa ter: rodada, time_casa, time_visitante")
        for linha in reader:
            try:
                rodada = int(linha["rodada"].strip())
                casa   = linha["time_casa"].strip()
                visit  = linha["time_visitante"].strip()
                rodadas[rodada].append((casa, visit))
            except ValueError:
                continue
    rodadas_dict = dict(sorted(rodadas.items()))
    with get_db() as db:
        db_save_jogos(db, rodadas_dict)
    return rodadas_dict


def listar_times(rodadas: dict) -> list:
    times: set = set()
    for jogos in rodadas.values():
        for casa, visit in jogos:
            times.add(casa)
            times.add(visit)
    return sorted(times)


def validar_celular(cel: str) -> bool:
    return len(re.sub(r"\D", "", cel)) in (10, 11)


def saldo_creditos(uid: str) -> int:
    with get_db() as db:
        return db_get_saldo(db, uid)


def creditar(uid: str, quantidade: int, motivo: str = "recarga admin"):
    with get_db() as db:
        db_add_credito(db, uid, quantidade, motivo)


def debitar_credito(uid: str, motivo: str = "entrada no grupo") -> bool:
    with get_db() as db:
        if db_get_saldo(db, uid) <= 0:
            return False
        db_add_credito(db, uid, -1, motivo)
    return True


def debitar_creditos_multiplos(uid: str, quantidade: int,
                               motivo: str = "entrada no grupo") -> bool:
    with get_db() as db:
        if db_get_saldo(db, uid) < quantidade:
            return False
        db_add_credito(db, uid, -quantidade, motivo)
    return True


def ja_debitou_entrada(uid: str, gid: str = "") -> bool:
    return len(funis_do_usuario(uid, gid)) > 0


def marcar_credito_debitado(uid: str, gid: str = ""):
    pass


def carregar_grupos() -> dict:
    with get_db() as db:
        return db_get_grupos(db)


def info_grupo(gid: str) -> dict:
    return carregar_grupos().get(gid, {})


def _proximo_id_grupo() -> str:
    grupos = carregar_grupos()
    return str(max((int(k) for k in grupos.keys()), default=0) + 1)


def total_apostas_grupo(gid: str) -> int:
    return len(funis_do_grupo(gid))


def apostas_disponiveis_grupo(gid: str) -> int:
    return LIMITE_GRUPO - total_apostas_grupo(gid)


def vagas_grupo(gid: str) -> int:
    return apostas_disponiveis_grupo(gid)


def grupo_esta_aberto(gid: str) -> bool:
    g       = info_grupo(gid)
    cfg     = carregar_config()
    r_ini   = cfg.get("rodada_inicial", 1)
    r_grupo = g.get("rodada_inicial_grupo", 1)
    r_at    = cfg.get("rodada_ativa", r_ini)
    return apostas_disponiveis_grupo(gid) > 0 and r_at <= r_grupo


def grupo_aceita_apostas(gid: str, qtd: int) -> bool:
    return apostas_disponiveis_grupo(gid) >= qtd


def alocar_grupo(uid: str) -> str:
    grupos = carregar_grupos()
    cfg    = carregar_config()
    r_ini  = cfg.get("rodada_inicial", 1)
    r_at   = cfg.get("rodada_ativa", r_ini)
    for gid in sorted(grupos.keys(), key=int):
        g = grupos[gid]
        if r_at <= g.get("rodada_inicial_grupo", 1) and apostas_disponiveis_grupo(gid) > 0:
            g["membros"].append(uid)
            with get_db() as db:
                db_save_grupo(db, gid, g)
            return gid
    novo_id = _proximo_id_grupo()
    with get_db() as db:
        db_save_grupo(db, novo_id, {
            "id": novo_id, "nome": f"Grupo {novo_id}",
            "membros": [uid], "rodada_inicial_grupo": r_at,
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        })
    return novo_id


def alocar_grupo_com_vagas(uid: str, qtd_times: int) -> str:
    grupos = carregar_grupos()
    cfg    = carregar_config()
    r_ini  = cfg.get("rodada_inicial", 1)
    r_at   = cfg.get("rodada_ativa", r_ini)
    for gid in sorted(grupos.keys(), key=int):
        g = grupos[gid]
        if r_at <= g.get("rodada_inicial_grupo", 1) and apostas_disponiveis_grupo(gid) >= qtd_times:
            if uid not in g["membros"]:
                g["membros"].append(uid)
                with get_db() as db:
                    db_save_grupo(db, gid, g)
            return gid
    novo_id = _proximo_id_grupo()
    with get_db() as db:
        db_save_grupo(db, novo_id, {
            "id": novo_id, "nome": f"Grupo {novo_id}",
            "membros": [uid], "rodada_inicial_grupo": r_at,
            "criado_em": datetime.now().isoformat(timespec="seconds"),
        })
    return novo_id


def carregar_funis() -> dict:
    with get_db() as db:
        return db_get_funis(db)


def salvar_funis(funis: dict):
    with get_db() as db:
        db_save_funis(db, funis)


def carregar_status() -> dict:
    return carregar_funis()


def salvar_status(status: dict):
    funis_validos = {k: v for k, v in status.items() if _funil_valido(v)}
    salvar_funis(funis_validos)


def _funil_valido(f: dict) -> bool:
    return isinstance(f, dict) and "gid" in f and "uid" in f and "rodada_inicio" in f


def _proximo_id_funil(uid: str, gid: str) -> str:
    funis      = carregar_funis()
    prefixo    = f"{uid}_{gid}_"
    existentes = [k for k in funis if k.startswith(prefixo)]
    return f"{prefixo}{len(existentes) + 1}"


def criar_funil(uid: str, gid: str, rodada_inicio: int, time_inicial: str) -> str:
    fid  = _proximo_id_funil(uid, gid)
    novo = {
        "id": fid, "uid": uid, "gid": gid,
        "rodada_inicio": rodada_inicio,
        "historico": [{"rodada": rodada_inicio, "time": time_inicial}],
        "times_usados": [time_inicial],
        "eliminado": False, "eliminado_na_rodada": None, "vencedor": False,
    }
    with get_db() as db:
        db_save_funis(db, {fid: novo})
    return fid


def funis_do_usuario(uid: str, gid: str = "") -> list:
    funis = carregar_funis()
    return [f for f in funis.values()
            if _funil_valido(f) and f["uid"] == uid and (not gid or f["gid"] == gid)]


def funis_vivos_usuario(uid: str, gid: str = "") -> list:
    funis = funis_do_usuario(uid, gid)

    if not funis:
        print(f"[WARN] Usuario {uid} sem funis")

    vivos = [f for f in funis if not f.get("eliminado", False)]

    print(f"[DEBUG] vivos={len(vivos)} total={len(funis)}")

    return vivos


def funis_do_grupo(gid: str) -> list:
    funis = carregar_funis()
    return [f for f in funis.values() if _funil_valido(f) and f["gid"] == gid]


def funis_vivos_grupo(gid: str) -> list:
    return [f for f in funis_do_grupo(gid) if not f.get("eliminado", False)]


def iniciar_status_usuario(uid: str, gid: str):
    pass


def todos_times_usados(uid: str, gid: str = "") -> list:
    usados: set = set()
    for f in funis_do_usuario(uid, gid):
        usados.update(f.get("times_usados", []))
    return list(usados)


def times_usados(uid: str, gid: str = "") -> list:
    return todos_times_usados(uid, gid)


def esta_eliminado(uid: str, gid: str = "") -> bool:
    todos = funis_do_usuario(uid, gid)
    if not todos:
        return False
    return all(f["eliminado"] for f in todos)


def e_vencedor(uid: str, gid: str = "") -> bool:
    return any(f.get("vencedor") for f in funis_do_usuario(uid, gid))


def ativos_do_grupo(gid: str) -> list:
    grupos  = carregar_grupos()
    membros = grupos.get(gid, {}).get("membros", [])
    return [uid for uid in membros if funis_vivos_usuario(uid, gid)]


def ativos_do_grupo_com_status(gid: str, status: dict) -> list:
    return ativos_do_grupo(gid)


def processar_eliminacao(gid: str, num_rodada: int):
    with get_db() as db:
        resultados = db_get_resultados(db)
        funis      = db_get_funis(db)
        apostas    = db_get_apostas(db)
        usuarios   = db_get_usuarios(db)

    chave_res = str(num_rodada)
    if chave_res not in resultados:
        return None

    vencedores_reais = set(resultados[chave_res]["vencedores"])
    funis_do_grp     = [f for f in funis.values()
                        if _funil_valido(f) and f["gid"] == gid and not f["eliminado"]]

    if not funis_do_grp:
        return {"_empate_coletivo": False, "_eliminados_agora": [], "_vencedor": None}

    relatorio: dict        = {}
    resultados_funil: dict = {}

    for f in funis_do_grp:
        fid          = f["id"]
        chave_aposta = f"{f['uid']}_{gid}_{num_rodada}_{fid}"
        aposta       = apostas.get(chave_aposta)
        if not aposta:
            resultados_funil[fid] = {"apostou": False, "time": None, "sobreviveu": None}
        else:
            time       = aposta["time"]
            sobreviveu = time in vencedores_reais
            resultados_funil[fid] = {"apostou": True, "time": time, "sobreviveu": sobreviveu}
        uid  = f["uid"]
        nome = usuarios.get(uid, {}).get("nome", uid)
        relatorio.setdefault(uid, {"nome": nome, "funis": {}})
        relatorio[uid]["funis"][fid] = resultados_funil[fid]

    apostaram         = [fid for fid, r in resultados_funil.items() if r["apostou"]]
    todos_eliminariam = bool(apostaram) and all(
        not resultados_funil[fid]["sobreviveu"] for fid in apostaram
    )
    relatorio["_empate_coletivo"] = todos_eliminariam

    eliminados_agora = []
    for f in funis_do_grp:
        fid = f["id"]
        r   = resultados_funil[fid]
        # mudança sugerida em 30/04
        if not r["apostou"]:
            f["eliminado"] = True
            f["eliminado_na_rodada"] = num_rodada

            f.setdefault("historico", []).append({
                "rodada": num_rodada,
                "time": None,
                "resultado": "nao_apostou"
            })

            eliminados_agora.append(fid)
            continue

        if todos_eliminariam:
            if r["time"] not in f["times_usados"]:
                f["times_usados"].append(r["time"])
            f["historico"].append({"rodada": num_rodada, "time": r["time"],
                                   "resultado": "empate_coletivo"})
        elif r["sobreviveu"]:
            if r["time"] not in f["times_usados"]:
                f["times_usados"].append(r["time"])
            f["historico"].append({"rodada": num_rodada, "time": r["time"],
                                   "resultado": "venceu"})
        else:
            f["eliminado"]           = True
            f["eliminado_na_rodada"] = num_rodada
            f["historico"].append({"rodada": num_rodada, "time": r["time"],
                                   "resultado": "eliminado"})
            eliminados_agora.append(fid)

    relatorio["_eliminados_agora"] = eliminados_agora

    funis_vivos_pos = [f for f in funis.values()
                       if _funil_valido(f) and f["gid"] == gid and not f["eliminado"]]
    uids_vivos = list({f["uid"] for f in funis_vivos_pos})

    if len(uids_vivos) == 1:
        vencedor_uid = uids_vivos[0]
        for f in funis.values():
            if _funil_valido(f) and f["gid"] == gid and f["uid"] == vencedor_uid and not f["eliminado"]:
                f["vencedor"] = True
        relatorio["_vencedor"] = vencedor_uid
    elif len(uids_vivos) == 0:
        for fid in eliminados_agora:
            funis[fid]["vencedor"]  = True
            funis[fid]["eliminado"] = False
        relatorio["_vencedor"] = [funis[fid]["uid"] for fid in eliminados_agora]
    else:
        relatorio["_vencedor"] = None

    salvar_funis(funis)
    return relatorio


def gerar_apostas_automaticas(num_rodada: int, rodadas: dict) -> list:
    with get_db() as db:
        apostas  = db_get_apostas(db)
        funis    = db_get_funis(db)
        grupos   = db_get_grupos(db)
        usuarios = db_get_usuarios(db)

    times_da_rodada: set = set()
    for casa, visit in rodadas.get(num_rodada, []):
        times_da_rodada.add(casa)
        times_da_rodada.add(visit)

    relatorio: list      = []
    novas_apostas: dict  = {}

    for gid, g in grupos.items():
        r_inicial = g.get("rodada_inicial_grupo", 1)
        if num_rodada <= r_inicial:
            continue
        for f in [f for f in funis.values()
                  if _funil_valido(f) and f["gid"] == gid and not f["eliminado"]]:
            fid          = f["id"]
            uid          = f["uid"]
            chave_aposta = f"{uid}_{gid}_{num_rodada}_{fid}"
            if chave_aposta in apostas:
                continue
            apostou_antes = any(h["rodada"] < num_rodada for h in f.get("historico", []))
            if not apostou_antes:
                relatorio.append({"fid": fid, "uid": uid, "gid": gid,
                                   "gerada": False, "motivo": "Funil novo — sem aposta anterior"})
                continue
            ja_usados   = set(f.get("times_usados", []))
            disponiveis = sorted(t for t in times_da_rodada if t not in ja_usados)
            if not disponiveis:
                relatorio.append({"fid": fid, "uid": uid, "gid": gid,
                                   "gerada": False, "motivo": "Sem times disponiveis"})
                continue
            time_auto = disponiveis[0]
            #correção sugerida em 30/04 chatGPT            
            novas_apostas[chave_aposta] = {
                "uid": uid, "gid": gid, "fid": fid,
                "rodada": num_rodada, "time": time_auto,
                "apostado_em": datetime.now().isoformat(timespec="seconds"),
                "automatica": True,
            }

            # NOVO BLOCO
            f.setdefault("times_usados", [])
            if time_auto not in f["times_usados"]:
                f["times_usados"].append(time_auto)

            f.setdefault("historico", []).append({
                "rodada": num_rodada,
                "time": time_auto,
                "resultado": "auto"
            })

            relatorio.append({
                "fid": fid, "uid": uid, "gid": gid, "gerada": True,
                "time": time_auto, "nome": usuarios.get(uid, {}).get("nome", uid),
            })

    if novas_apostas:
        with get_db() as db:
            db_save_apostas(db, novas_apostas)
            db_save_funis(db, funis)

    return relatorio
