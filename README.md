# Bolão Survivor — Web

Sistema de bolão survivor com grupos de apostas por rodada.

## Stack
- **Backend**: FastAPI + Python
- **Banco**: PostgreSQL (SQLAlchemy 2.0 + psycopg2)
- **Frontend**: React + Tailwind + Vite
- **Auth**: JWT
- **Deploy**: Railway (plugin PostgreSQL nativo)

## Estrutura
```
bolao/
├── backend/
│   ├── main.py        ← API FastAPI (25+ rotas)
│   ├── core.py        ← Lógica de negócio (PostgreSQL)
│   ├── db.py          ← Modelos SQLAlchemy + helpers CRUD
│   ├── auth.py        ← JWT
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/     ← Login, Cadastro, Dashboard, Apostas, Grupos, AdminPanel
│   │   ├── components/← Layout
│   │   ├── api.js     ← Cliente axios
│   │   └── store.js   ← Zustand auth
│   └── package.json
├── jogos.csv          ← Jogos do campeonato
├── Dockerfile
└── railway.toml
```

## Desenvolvimento local

### 1. Suba um PostgreSQL local
```bash
docker run -d --name bolao-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=bolao \
  -p 5432:5432 postgres:16
```

### 2. Backend
```bash
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bolao
export JOGOS_CSV=../jogos.csv
uvicorn main:app --reload --port 8000
```
As tabelas são criadas automaticamente no primeiro start.

### 3. Frontend
```bash
cd frontend
npm install
npm run dev   # proxy para localhost:8000
```

Acesse: http://localhost:5173

### Admin
Login: celular = `admin`, senha = `admin123`  
Altere `SENHA_ADMIN` e `SECRET_KEY` via variável de ambiente em produção.

## Deploy no Railway

1. Crie conta em [railway.app](https://railway.app)
2. Novo projeto → **Add Service → Database → PostgreSQL**
3. Novo serviço → **Deploy from GitHub** (aponte para este repo)
4. Na aba **Variables** do serviço web, adicione:
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   SECRET_KEY=sua-chave-secreta-longa-aqui
   SENHA_ADMIN=senha-forte-do-admin
   ```
5. Deploy automático via Dockerfile

## Variáveis de ambiente

| Variável        | Padrão                          | Descrição                     |
|-----------------|---------------------------------|-------------------------------|
| `DATABASE_URL`  | `postgresql://...localhost/bolao`| URL do PostgreSQL             |
| `SECRET_KEY`    | (inseguro)                      | Chave JWT — mude em produção  |
| `SENHA_ADMIN`   | `admin123`                      | Senha do painel admin         |
| `JOGOS_CSV`     | `jogos.csv`                     | Caminho do CSV de jogos       |
| `PORT`          | `8000`                          | Porta do servidor             |

## Esquema do banco

| Tabela          | Descrição                                      |
|-----------------|------------------------------------------------|
| `config`        | Chave-valor de configuração do sistema         |
| `usuarios`      | Apostadores cadastrados                        |
| `grupos`        | Grupos de aposta                               |
| `grupo_membros` | Relacionamento N:N usuário ↔ grupo             |
| `funis`         | Funis individuais (histórico + status)         |
| `apostas`       | 1 aposta por funil por rodada                  |
| `resultados`    | Vencedores de cada rodada                      |
| `creditos`      | Lançamentos de crédito/débito por usuário      |
| `jogos`         | Jogos carregados do CSV (cache)                |

## jogos.csv
```csv
rodada,time_casa,time_visitante
1,Flamengo,Palmeiras
1,Santos,Gremio
...
```

## API — principais endpoints

| Método | Rota                        | Descrição                    |
|--------|-----------------------------|------------------------------|
| POST   | /api/auth/login             | Login (retorna JWT)          |
| POST   | /api/auth/cadastro          | Novo apostador               |
| GET    | /api/usuario/situacao       | Funis e status do usuário    |
| GET    | /api/usuario/creditos       | Saldo e histórico            |
| GET    | /api/rodadas                | Info da rodada ativa         |
| POST   | /api/apostas/nova-entrada   | Cria funis (debita créditos) |
| POST   | /api/apostas/continuar-funil| Aposta em funil vivo         |
| PUT    | /api/apostas/alterar        | Altera aposta desta rodada   |
| GET    | /api/grupos                 | Lista grupos e apostadores   |
| POST   | /api/admin/abrir-rodada     | Abre rodada (admin)          |
| POST   | /api/admin/resultado        | Insere resultado (admin)     |

Documentação interativa: http://localhost:8000/docs
