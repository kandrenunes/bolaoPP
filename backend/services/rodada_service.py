from backend.core import gerar_apostas_automaticas, processar_eliminacao
from backend.core import (
    gerar_apostas_automaticas,
    processar_eliminacao,
    carregar_config,
    salvar_config,
    prazo_expirado
    )
from backend.db import get_db, db_get_grupos

def fechar_rodada(num_rodada: int, rodadas: dict):
    cfg = carregar_config()

    if not prazo_expirado():
        raise Exception("Prazo ainda não expirou")

    print(f"[RODADA] Fechando rodada {num_rodada}")

    rel_auto = gerar_apostas_automaticas(num_rodada, rodadas)

    with get_db() as db:
        grupos = db_get_grupos(db)

    relatorios = {}
    for gid in grupos.keys():
        relatorios[gid] = processar_eliminacao(gid, num_rodada)

    cfg["rodada_ativa"] = num_rodada + 1
    cfg["prazo_apostas"] = ""

    salvar_config(cfg)

    return {
        "rodada_fechada": num_rodada,
        "proxima": cfg["rodada_ativa"],
        "auto": rel_auto,
        "eliminacao": relatorios
    }