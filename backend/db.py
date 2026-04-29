"""
db.py — Camada de persistência PostgreSQL para o Bolão Survivor.

Esquema:
  config    — row única com configuração do sistema (rodada_inicial, prazo etc.)
  usuarios  — apostadores cadastrados
  grupos    — grupos de aposta
  funis     — funis individuais (1 por time apostado na entrada)
  apostas   — aposta de um funil em uma rodada específica
  resultados— resultado de cada rodada (vencedores)
  creditos  — saldo e histórico de créditos por usuário
  jogos     — jogos carregados do CSV (cache em DB)
"""

import os, json
from contextlib import contextmanager
from sqlalchemy import (
    create_engine, Column, String, Integer, Boolean,
    Text, DateTime, ForeignKey, UniqueConstraint, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from datetime import datetime

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/bolao"
)
# Railway usa "postgres://..." — SQLAlchemy exige "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"sslmode": "require"}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Modelos ──────────────────────────────────────────────────────────────────

class Config(Base):
    __tablename__ = "config"
    chave  = Column(String(64), primary_key=True)
    valor  = Column(Text, nullable=False)      # JSON serializado


class Usuario(Base):
    __tablename__ = "usuarios"
    celular       = Column(String(20),  primary_key=True)
    nome          = Column(String(120), nullable=False)
    celular_fmt   = Column(String(30))
    whatsapp      = Column(Boolean, default=False)
    email         = Column(String(120), default="")
    cpf           = Column(String(14),  default="")
    pix           = Column(String(120), nullable=False)
    senha_hash    = Column(String(64),  nullable=False)
    time_coracao  = Column(String(80),  default="")
    cadastro_em   = Column(DateTime,    default=datetime.utcnow)


class Grupo(Base):
    __tablename__ = "grupos"
    id                    = Column(String(20), primary_key=True)
    nome                  = Column(String(80), nullable=False)
    rodada_inicial_grupo  = Column(Integer,    nullable=False)
    criado_em             = Column(DateTime,   default=datetime.utcnow)


class GrupoMembro(Base):
    __tablename__ = "grupo_membros"
    grupo_id  = Column(String(20), ForeignKey("grupos.id"), primary_key=True)
    usuario_id = Column(String(20), ForeignKey("usuarios.celular"), primary_key=True)


class Funil(Base):
    __tablename__ = "funis"
    id                   = Column(String(80),  primary_key=True)
    uid                  = Column(String(20),  ForeignKey("usuarios.celular"), nullable=False)
    gid                  = Column(String(20),  ForeignKey("grupos.id"),        nullable=False)
    rodada_inicio        = Column(Integer,     nullable=False)
    historico            = Column(Text,        default="[]")   # JSON list
    times_usados         = Column(Text,        default="[]")   # JSON list
    eliminado            = Column(Boolean,     default=False)
    eliminado_na_rodada  = Column(Integer,     nullable=True)
    vencedor             = Column(Boolean,     default=False)


class Aposta(Base):
    __tablename__ = "apostas"
    __table_args__ = (UniqueConstraint("uid", "gid", "rodada", "fid"),)
    id          = Column(Integer,    primary_key=True, autoincrement=True)
    uid         = Column(String(20), ForeignKey("usuarios.celular"), nullable=False)
    gid         = Column(String(20), ForeignKey("grupos.id"),        nullable=False)
    fid         = Column(String(80), ForeignKey("funis.id"),         nullable=False)
    rodada      = Column(Integer,    nullable=False)
    time        = Column(String(80), nullable=False)
    apostado_em = Column(DateTime,   default=datetime.utcnow)
    automatica  = Column(Boolean,    default=False)


class Resultado(Base):
    __tablename__ = "resultados"
    rodada      = Column(Integer, primary_key=True)
    vencedores  = Column(Text,    default="[]")   # JSON list
    inserido_em = Column(DateTime, default=datetime.utcnow)


class Credito(Base):
    __tablename__ = "creditos"
    id        = Column(Integer,    primary_key=True, autoincrement=True)
    uid       = Column(String(20), ForeignKey("usuarios.celular"), nullable=False)
    valor     = Column(Integer,    nullable=False)    # + crédito, - débito
    motivo    = Column(String(200), default="")
    criado_em = Column(DateTime,   default=datetime.utcnow)


class Jogo(Base):
    __tablename__ = "jogos"
    __table_args__ = (UniqueConstraint("rodada", "posicao"),)
    id      = Column(Integer,   primary_key=True, autoincrement=True)
    rodada  = Column(Integer,   nullable=False)
    posicao = Column(Integer,   nullable=False)  # ordem dentro da rodada
    casa    = Column(String(80), nullable=False)
    visit   = Column(String(80), nullable=False)


# ── Setup ────────────────────────────────────────────────────────────────────

def init_db():
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Helpers CRUD (usados pelo core.py) ───────────────────────────────────────

# CONFIG
def db_get_config(db: Session) -> dict:
    rows = db.query(Config).all()
    result = {}
    for row in rows:
        try:
            result[row.chave] = json.loads(row.valor)
        except (json.JSONDecodeError, TypeError):
            result[row.chave] = row.valor
    return result


def db_set_config(db: Session, cfg: dict):
    for chave, valor in cfg.items():
        serializado = json.dumps(valor) if not isinstance(valor, str) else json.dumps(valor)
        row = db.query(Config).filter_by(chave=chave).first()
        if row:
            row.valor = serializado
        else:
            db.add(Config(chave=chave, valor=serializado))


# USUÁRIOS
def db_get_usuarios(db: Session) -> dict:
    rows = db.query(Usuario).all()
    result = {}
    for u in rows:
        grupos = [gm.grupo_id for gm in db.query(GrupoMembro).filter_by(usuario_id=u.celular).all()]
        result[u.celular] = {
            "nome": u.nome, "celular": u.celular,
            "celular_fmt": u.celular_fmt, "whatsapp": u.whatsapp,
            "email": u.email, "cpf": u.cpf, "pix": u.pix,
            "senha": u.senha_hash, "time_coracao": u.time_coracao,
            "grupos": grupos,
            "cadastro_em": u.cadastro_em.isoformat() if u.cadastro_em else "",
        }
    return result


def db_save_usuario(db: Session, uid: str, data: dict):
    u = db.query(Usuario).filter_by(celular=uid).first()
    if u:
        u.nome         = data.get("nome", u.nome)
        u.celular_fmt  = data.get("celular_fmt", u.celular_fmt)
        u.whatsapp     = data.get("whatsapp", u.whatsapp)
        u.email        = data.get("email", u.email)
        u.cpf          = data.get("cpf", u.cpf)
        u.pix          = data.get("pix", u.pix)
        u.senha_hash   = data.get("senha", u.senha_hash)
        u.time_coracao = data.get("time_coracao", u.time_coracao)
    else:
        db.add(Usuario(
            celular=uid, nome=data["nome"],
            celular_fmt=data.get("celular_fmt", uid),
            whatsapp=data.get("whatsapp", False),
            email=data.get("email", ""), cpf=data.get("cpf", ""),
            pix=data.get("pix", uid), senha_hash=data["senha"],
            time_coracao=data.get("time_coracao", ""),
        ))
    # Sincroniza grupos
    grupos_novos = set(data.get("grupos", []))
    grupos_atuais = {gm.grupo_id for gm in db.query(GrupoMembro).filter_by(usuario_id=uid).all()}
    for gid in grupos_novos - grupos_atuais:
        db.add(GrupoMembro(grupo_id=gid, usuario_id=uid))


# GRUPOS
def db_get_grupos(db: Session) -> dict:
    result = {}
    for g in db.query(Grupo).all():
        membros = [gm.usuario_id for gm in db.query(GrupoMembro).filter_by(grupo_id=g.id).all()]
        result[g.id] = {
            "id": g.id, "nome": g.nome,
            "rodada_inicial_grupo": g.rodada_inicial_grupo,
            "membros": membros,
            "criado_em": g.criado_em.isoformat() if g.criado_em else "",
        }
    return result


def db_save_grupo(db: Session, gid: str, data: dict):
    g = db.query(Grupo).filter_by(id=gid).first()
    if g:
        g.nome                 = data.get("nome", g.nome)
        g.rodada_inicial_grupo = data.get("rodada_inicial_grupo", g.rodada_inicial_grupo)
    else:
        db.add(Grupo(
            id=gid, nome=data["nome"],
            rodada_inicial_grupo=data["rodada_inicial_grupo"],
        ))
    # Sincroniza membros
    membros_novos   = set(data.get("membros", []))
    membros_atuais  = {gm.usuario_id for gm in db.query(GrupoMembro).filter_by(grupo_id=gid).all()}
    for uid in membros_novos - membros_atuais:
        db.add(GrupoMembro(grupo_id=gid, usuario_id=uid))


def db_save_grupos(db: Session, grupos: dict):
    for gid, data in grupos.items():
        db_save_grupo(db, gid, data)


# FUNIS
def db_get_funis(db: Session) -> dict:
    result = {}
    for f in db.query(Funil).all():
        result[f.id] = {
            "id": f.id, "uid": f.uid, "gid": f.gid,
            "rodada_inicio": f.rodada_inicio,
            "historico": json.loads(f.historico or "[]"),
            "times_usados": json.loads(f.times_usados or "[]"),
            "eliminado": f.eliminado,
            "eliminado_na_rodada": f.eliminado_na_rodada,
            "vencedor": f.vencedor,
        }
    return result


def db_save_funis(db: Session, funis: dict):
    for fid, data in funis.items():
        f = db.query(Funil).filter_by(id=fid).first()
        if f:
            f.historico           = json.dumps(data.get("historico", []))
            f.times_usados        = json.dumps(data.get("times_usados", []))
            f.eliminado           = data.get("eliminado", False)
            f.eliminado_na_rodada = data.get("eliminado_na_rodada")
            f.vencedor            = data.get("vencedor", False)
        else:
            db.add(Funil(
                id=fid, uid=data["uid"], gid=data["gid"],
                rodada_inicio=data["rodada_inicio"],
                historico=json.dumps(data.get("historico", [])),
                times_usados=json.dumps(data.get("times_usados", [])),
                eliminado=data.get("eliminado", False),
                eliminado_na_rodada=data.get("eliminado_na_rodada"),
                vencedor=data.get("vencedor", False),
            ))


# APOSTAS
def db_get_apostas(db: Session) -> dict:
    result = {}
    for a in db.query(Aposta).all():
        chave = f"{a.uid}_{a.gid}_{a.rodada}_{a.fid}"
        result[chave] = {
            "uid": a.uid, "gid": a.gid, "fid": a.fid,
            "rodada": a.rodada, "time": a.time,
            "apostado_em": a.apostado_em.isoformat() if a.apostado_em else "",
            "automatica": a.automatica,
        }
    return result


def db_save_apostas(db: Session, apostas: dict):
    for chave, data in apostas.items():
        existing = db.query(Aposta).filter_by(
            uid=data["uid"], gid=data["gid"],
            rodada=data["rodada"], fid=data["fid"]
        ).first()
        if existing:
            existing.time       = data["time"]
            existing.automatica = data.get("automatica", False)
            existing.apostado_em = datetime.utcnow()
        else:
            db.add(Aposta(
                uid=data["uid"], gid=data["gid"], fid=data["fid"],
                rodada=data["rodada"], time=data["time"],
                automatica=data.get("automatica", False),
            ))


# RESULTADOS
def db_get_resultados(db: Session) -> dict:
    result = {}
    for r in db.query(Resultado).all():
        result[str(r.rodada)] = {
            "rodada": r.rodada,
            "vencedores": json.loads(r.vencedores or "[]"),
            "inserido_em": r.inserido_em.isoformat() if r.inserido_em else "",
        }
    return result


def db_save_resultado(db: Session, rodada: int, vencedores: list):
    r = db.query(Resultado).filter_by(rodada=rodada).first()
    if r:
        r.vencedores = json.dumps(vencedores)
        r.inserido_em = datetime.utcnow()
    else:
        db.add(Resultado(rodada=rodada, vencedores=json.dumps(vencedores)))


# CRÉDITOS
def db_get_saldo(db: Session, uid: str) -> int:
    rows = db.query(Credito).filter_by(uid=uid).all()
    return sum(r.valor for r in rows)


def db_get_creditos_usuario(db: Session, uid: str) -> dict:
    rows = db.query(Credito).filter_by(uid=uid).order_by(Credito.criado_em).all()
    historico = [
        {
            "tipo": "credito" if r.valor > 0 else "debito",
            "valor": r.valor,
            "motivo": r.motivo,
            "data": r.criado_em.isoformat() if r.criado_em else "",
        }
        for r in rows
    ]
    return {"saldo": sum(r.valor for r in rows), "historico": historico}


def db_add_credito(db: Session, uid: str, valor: int, motivo: str):
    db.add(Credito(uid=uid, valor=valor, motivo=motivo))


# JOGOS
def db_save_jogos(db: Session, rodadas: dict):
    """Persiste jogos do CSV no banco (upsert por rodada+posicao)."""
    for num_rodada, jogos in rodadas.items():
        for i, (casa, visit) in enumerate(jogos, 1):
            existing = db.query(Jogo).filter_by(rodada=num_rodada, posicao=i).first()
            if not existing:
                db.add(Jogo(rodada=num_rodada, posicao=i, casa=casa, visit=visit))


def db_get_jogos(db: Session) -> dict:
    result: dict = {}
    for j in db.query(Jogo).order_by(Jogo.rodada, Jogo.posicao).all():
        result.setdefault(j.rodada, []).append((j.casa, j.visit))
    return result
