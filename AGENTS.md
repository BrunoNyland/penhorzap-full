# AGENTS.md — PenhorZap monorepo

Bot de WhatsApp com IA (Google Gemini) para casa de penhores. Django 5.2 + django-q2 + Evolution API no backend; Angular 19 SPA no painel admin. UI e prompts em pt-BR; `TIME_ZONE = America/Sao_Paulo`.

Para detalhes do backend Django (apps, invariantes de privacidade, fluxo de mensagens, modelo de dados), leia **`www/AGENTS.md`** — este arquivo cobre só o que é específico do monorepo e do runtime.

## Layout

```
/var/www/pwa.brunonyland.com/        <- repo root = PROJECT_ROOT do Django
├── www/                             <- backend Django (manage.py, settings, apps api/core/ia/painel/whatsapp)
├── frontend/                        <- Angular 19 SPA, build -> frontend/dist/frontend/browser/ (servida em /painel/ pelo nginx)
├── evolution/docker-compose.yml     <- Evolution API (WhatsApp) + Postgres, em 127.0.0.1:8080
├── Makefile                         <- test/lint/build/deploy
├── deploy.sh                        <- deploy completo (test -> migrate -> build -> collectstatic -> restart)
├── graphify-out/                    <- knowledge graph (ver CLAUDE.md)
├── .env                             <- TODAS as env vars (não há .env dentro de www/ nem frontend/)
├── venv/                            <- Python 3.12 (gitignored)
├── staticfiles/  media/             <- saídas do collectstatic / uploads (gitignored)
└── db.sqlite3                       <- só quando DB_ENGINE != mysql
```

## Runtime root é o pai de `www/`

`www/penhorzap/settings.py:11-15` define `BASE_DIR = .../www` e `PROJECT_ROOT = BASE_DIR.parent` (= este diretório). Carrega `.env` e `db.sqlite3` a partir de `PROJECT_ROOT`, não de `www/`. **Não procure `.env` dentro de `www/`.** Rode `manage.py` sempre a partir de `www/` com `../venv/bin/python` (ou ative o venv com `source ../venv/bin/activate`).

## Serviços em produção (systemd)

- `gunicorn@pwa.brunonyland.com.service` — web (wsgi). Config de env em `gunicorn.env` (só `DJANGO_WSGI=wsgi:application`).
- `penhorzap-qcluster.service` — fila django-q2 (executa tasks async). **Separado do gunicorn.**
- nginx na frente; `nginx -t` antes de reload (deploy.sh e Makefile validam).

## Dois processos — gotcha crítico

O `qcluster` executa as tasks; o gunicorn/runserver só servem HTTP. **Mudanças em `whatsapp/tasks.py`, `api/tasks.py` ou `ia/services.py` exigem restart do qcluster** — o processo web não recarrega esse código.

⚠️ `make deploy` reinicia **apenas gunicorn + nginx**, NÃO o qcluster. Use `./deploy.sh` (reinicia qcluster se ativo) ou reinicie manualmente: `systemctl restart penhorzap-qcluster.service`. Esse é o único motivo prático para preferir `deploy.sh` ao `make deploy`.

## Comandos

Tudo via Makefile ou deploy.sh. Sem lint/format/typecheck/CI configurados; não há pytest/tox. Os `*/tests.py` do Django em sua maioria são stubs — só `api` tem testes reais (~41 unit + `tests_integration`).

```bash
make test          # DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 ... manage.py test api -v2
make test-int      # testes de integração (api.tests_integration) — não-bloqueante no deploy.sh
make lint          # manage.py check --deploy + makemigrations --check + ng build prod + nginx -t
make build         # ng build --base-href /painel/ --configuration production
make deploy        # build + collectstatic + restart gunicorn/nginx (NÃO toca qcluster — ver acima)
make restart       # só reinicia gunicorn + nginx, sem rebuild
make all           # test + build + deploy

# teste unitário isolado
( cd www && DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 ../venv/bin/python manage.py test api.tests_integration.AlgoCRMTestCase.test_algo -v2 )

./deploy.sh            # test -> migrate -> build -> collectstatic -> restart (qcluster incluído)
./deploy.sh --skip-tests
./deploy.sh --test-only
```

`make test` força `DB_ENGINE=sqlite` e `DJANGO_IS_PRODUCTION=0` (SQLite em temp, sem redirect HTTPS) — rode testes pelo Makefile, não direto, senão o env de prod (MySQL) vaza.

## Frontend (Angular)

`frontend/` é um projeto Angular CLI 19 autônomo (não é o root `package.json`, que só tem `impeccable`). Dev server: `cd frontend && npx ng serve` com `proxy.conf.json` roteando `/api` e `/media` para `127.0.0.1:8000`. Build produção: `make build` (define `--base-href /painel/`). Saída em `frontend/dist/frontend/browser/`, servida por nginx em `/painel/`.

## Evolution API (WhatsApp)

`evolution/docker-compose.yml` sobe Postgres 16 + `evoapicloud/evolution-api:v2.3.7` em `127.0.0.1:8080` (rede `penhorzap_net`, Postgres não exposto no host). Webhook global -> `https://pwa.brunonyland.com/webhook/whatsapp/` (header `X-Webhook-Token` = `WEBHOOK_TOKEN` do `.env`). Sem Redis; cache local em memória (configuração do compose).

## VPS rules (do ~/.claude/CLAUDE.md)

- **Nunca instale pacotes Python como root** (sem `pip install`/`pipx`/`uv` com sudo ou `--break-system-packages`). Use o `venv/` existente ou crie um em `/tmp/opencode/venv-*`. Reinstalar pacotes dpkg com `apt-get install --reinstall` é permitido.

## Graphify

`graphify-out/graph.json` existe. Para perguntas sobre o codebase, rode `graphify query "<pergunta>"` / `graphify path "<A>" "<B>"` / `graphify explain "<conceito>"` antes de grep bruto. Depois de mexer no código, `graphify update .` (só AST, sem custo de API). Detalhes em `CLAUDE.md`.