# `penhorzap/` — configuração do projeto + entrypoints

Configuração Django do projeto: settings, URL raiz, ASGI/WSGI. Tudo que é
"infraestrutura" de config fica aqui (e nos entrypoints na raiz do repo).

## Arquivos

| Arquivo | O que faz | Editar quando... |
|---|---|---|
| `settings.py` | Config Django: `.env` via `dotenv` (em `PROJECT_ROOT/.env`), `DEBUG`/`ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`, MySQL vs SQLite (env-driven), apps, middleware, `EVOLUTION_*`/`GEMINI_API_KEY`/`WEBHOOK_TOKEN`, `Q_CLUSTER` (django-q2), `REST_FRAMEWORK`/`SPECTACULAR_SETTINGS`, hardening de prod. | quiser mudar config de ambiente, DB, filas, API, ou segurança. |
| `urls.py` | URL raiz: `/` → dashboard, `/admin/`, `whatsapp`, `/api/`, `/painel/`. Set `admin.site.login_template` e `site_header`. | quiser mudar a árvore de URLs raiz ou o branding do login admin. |
| `asgi.py` | Entry point ASGI (deploy async). | raramente. |
| `wsgi.py` (na **raiz do repo**, `www/wsgi.py`) | Entry point WSGI (gunicorn). Carrega `.env`. `WSGI_APPLICATION = "wsgi.application"`. | raramente. |
| `manage.py` (na raiz) | CLI; carrega `.env` de `PROJECT_ROOT`. | raramente. |
| `__init__.py` | vazio. | — |

## Quero um comportamento — onde edito?

- Mudar uma **variável de ambiente** → `PROJECT_ROOT/.env` (fora do repo) — não edite settings p/ isso.
- Mudar o **banco** (MySQL↔SQLite) → `.env` (`DB_ENGINE`); detalhes de conexão em `settings.py:DATABASES`.
- Mudar **ALLOWED_HOSTS/CSRF/SSL** → `settings.py`.
- Mudar **filas/workers** do django-q2 → `settings.py:Q_CLUSTER` (+ restart do qcluster).
- Mudar **autenticação/permissões/paginação da API** → `settings.py:REST_FRAMEWORK`.
- Mudar a **URL raiz** de um app ou o branding do login admin → `urls.py`.
- Mudar **modelo do Gemini / URL da Evolution / token do webhook** → `.env` (lidos em `settings.py`).

## Gotchas

- `BASE_DIR` = `www/`; `PROJECT_ROOT` = `BASE_DIR.parent` (onde `.env`/`venv`/`staticfiles`/`media`/`db.sqlite3` vivem, gitignored).
- `WSGI_APPLICATION = "wsgi.application"` — o `wsgi.py` está na **raiz do repo**, não em `penhorzap/`.
- DB engine é env-driven: `DB_ENGINE=mysql` → MySQL (utf8mb4); qualquer outro → SQLite em `PROJECT_ROOT/db.sqlite3`.
- Em prod (`DJANGO_IS_PRODUCTION=1`): SSL redirect, cookies secure.

Veja também: `../AGENTS.md` (layout/commands) e `../README.md` (visão geral/setup).
