#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Script de deploy automatizado para PenhorZap
# =============================================================================
# Uso:
#   ./deploy.sh              — Deploy completo (test + build + deploy)
#   ./deploy.sh --skip-tests — Pula testes, só faz build + deploy
#   ./deploy.sh --test-only  — Só roda testes, sem deploy
# =============================================================================
set -euo pipefail

# ── Cores ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()   { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
ok()    { echo -e "${GREEN}[✅]${NC} $1"; }
warn()  { echo -e "${YELLOW}[⚠️]${NC} $1"; }
fail()  { echo -e "${RED}[❌]${NC} $1"; exit 1; }

# ── Diretórios ─────────────────────────────────────────────────────────────────
PROJECT_DIR="/var/www/pwa.brunonyland.com"
WWW_DIR="$PROJECT_DIR/www"
FRONTEND_DIR="$PROJECT_DIR/frontend"
BACKUPS_DIR="$PROJECT_DIR/backups"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
GUNICORN_SVC="gunicorn@pwa.brunonyland.com.service"
QCLUSTER_SVC="penhorzap-qcluster.service"
BACKUPS_TO_KEEP=7

cd "$PROJECT_DIR"

# ── Flags ──────────────────────────────────────────────────────────────────────
SKIP_TESTS=false
TEST_ONLY=false

for arg in "$@"; do
    case $arg in
        --skip-tests) SKIP_TESTS=true ;;
        --test-only)  TEST_ONLY=true ;;
        *) warn "Flag desconhecida: $arg" ;;
    esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              PenhorZap — Deploy Automatizado                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Etapa 0: Dependências Python ──────────────────────────────────────────────
# uv sync é exato: instala o que o uv.lock pede e remove o que não está nele.
# Sem mudança no lock, não faz nada. O Python vem de /opt/uv-python (o www-data
# precisa executar o interpretador; em /root não conseguiria). venv/ é link
# para .venv/ (systemd e o template gunicorn@ usam venv/).
log "📋 Etapa 0: Dependências Python (uv sync --locked)..."
UV_PYTHON_INSTALL_DIR=/opt/uv-python /root/.local/bin/uv sync --locked
chmod -R a+rX "$PROJECT_DIR/.venv"
ok "Dependências em dia."
echo ""

# ── Etapa 1: Testes ────────────────────────────────────────────────────────────
if [ "$SKIP_TESTS" = false ]; then
    log "📋 Etapa 1a: Ruff..."
    "$PROJECT_DIR/venv/bin/ruff" check www || fail "Ruff encontrou problemas. Deploy abortado."
    ok "Ruff sem apontamentos."

    log "📋 Etapa 1: Rodando testes (api, core, whatsapp, ia)..."
    cd "$WWW_DIR"

    if DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 "$VENV_PYTHON" manage.py test api core whatsapp ia -v2 2>&1; then
        ok "Testes passaram!"
    else
        fail "Testes falharam. Deploy abortado."
    fi

    echo ""
    log "📋 Etapa 1b: Rodando testes de integração..."
    if DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 "$VENV_PYTHON" manage.py test api.tests_integration -v2 2>&1; then
        ok "Testes de integração passaram!"
    else
        warn "Testes de integração falharam (não-bloqueante)."
    fi

    cd "$PROJECT_DIR"
    echo ""

    if [ "$TEST_ONLY" = true ]; then
        ok "Testes concluídos. Flag --test-only ativa, saindo."
        exit 0
    fi
else
    warn "Testes pulados (--skip-tests)."
fi

# ── Etapa 2: Django deploy checks (gate bloqueante) ───────────────────────────
log "📋 Etapa 2: Rodando 'manage.py check --deploy'..."
cd "$WWW_DIR"

if "$VENV_PYTHON" manage.py check --deploy 2>&1; then
    ok "check --deploy passou sem erros."
else
    fail "'manage.py check --deploy' encontrou problemas. Deploy abortado — corrija antes de prosseguir."
fi

cd "$PROJECT_DIR"
echo ""

# ── Etapa 3: Backup do banco de dados (pré-migrate) ───────────────────────────
log "📋 Etapa 3: Backup do banco de dados..."

mkdir -p "$BACKUPS_DIR"

# Lê DB_ENGINE (e credenciais do PostgreSQL, se aplicável) do .env em PROJECT_ROOT.
DB_ENGINE_FROM_ENV=""
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.env"
    set +a
    DB_ENGINE_FROM_ENV="${DB_ENGINE:-}"
fi

TIMESTAMP="$(date +%F-%H%M%S)"

if [ "$DB_ENGINE_FROM_ENV" = "postgresql" ]; then
    # Formato custom (-Fc): já comprimido; restaura com pg_restore.
    BACKUP_FILE="$BACKUPS_DIR/db-$TIMESTAMP.dump"
    if PGPASSWORD="${DB_PASSWORD:-}" pg_dump -Fc \
            --host="${DB_HOST:-127.0.0.1}" \
            --port="${DB_PORT:-5432}" \
            --username="${DB_USER:-}" \
            --file="$BACKUP_FILE" \
            "${DB_NAME:-}"; then
        ok "Backup PostgreSQL criado em $BACKUP_FILE."
    else
        fail "Backup do PostgreSQL falhou. Deploy abortado (não seguimos sem backup)."
    fi
else
    SQLITE_DB="$PROJECT_DIR/db.sqlite3"
    BACKUP_FILE="$BACKUPS_DIR/db-$TIMESTAMP.sqlite3"
    if [ -f "$SQLITE_DB" ]; then
        if cp "$SQLITE_DB" "$BACKUP_FILE"; then
            ok "Backup SQLite criado em $BACKUP_FILE."
        else
            fail "Backup do SQLite falhou. Deploy abortado (não seguimos sem backup)."
        fi
    else
        warn "db.sqlite3 não encontrado em $SQLITE_DB — nada para copiar (banco pode ainda não existir)."
    fi
fi

# Retém apenas os 7 backups mais recentes.
if [ -d "$BACKUPS_DIR" ]; then
    (cd "$BACKUPS_DIR" && ls -t | tail -n +$((BACKUPS_TO_KEEP + 1)) | xargs -r rm -f)
fi

echo ""

# ── Etapa 4: Migrations ───────────────────────────────────────────────────────
log "📋 Etapa 4: Verificando migrations pendentes..."
cd "$WWW_DIR"

if "$VENV_PYTHON" manage.py showmigrations 2>&1 | grep -q '\[ \]'; then
    log "Aplicando migrations pendentes..."
    "$VENV_PYTHON" manage.py migrate
    ok "Migrations aplicadas."
else
    ok "Nenhuma migration pendente."
fi

cd "$PROJECT_DIR"
echo ""

# ── Etapa 5: Build Angular ────────────────────────────────────────────────────
log "📋 Etapa 5: Build do Angular SPA..."
cd "$FRONTEND_DIR"

# Builda em dist/novo e só troca se passar: o ng build apaga a pasta de saída
# antes de compilar, e o nginx serve o painel direto de dist/frontend/browser.
# Buildar no lugar e falhar deixaria o painel fora do ar.
rm -rf dist/novo dist/antigo
if npx ng build --base-href /painel/ --configuration production --output-path dist/novo 2>&1; then
    [ -d dist/frontend ] && mv dist/frontend dist/antigo
    mv dist/novo dist/frontend
    rm -rf dist/antigo
    ok "Angular build concluído."
else
    rm -rf dist/novo
    fail "Angular build falhou. Deploy abortado (o painel no ar não foi tocado)."
fi

cd "$PROJECT_DIR"
echo ""

# ── Etapa 6: Collect Static ───────────────────────────────────────────────────
log "📋 Etapa 6: Coletando arquivos estáticos..."
cd "$WWW_DIR"

"$VENV_PYTHON" manage.py collectstatic --noinput 2>&1 | tail -3
ok "Estáticos coletados."

cd "$PROJECT_DIR"
echo ""

# ── Etapa 7: Restart Services ─────────────────────────────────────────────────
log "📋 Etapa 7: Reiniciando serviços..."

# Testar Nginx antes de recarregar
if nginx -t 2>&1; then
    systemctl reload nginx
    ok "Nginx recarregado."
else
    fail "Configuração Nginx inválida. Deploy abortado."
fi

systemctl restart "$GUNICORN_SVC"
ok "Gunicorn reiniciado."

if systemctl is-active --quiet "$QCLUSTER_SVC" 2>/dev/null; then
    systemctl restart "$QCLUSTER_SVC"
    ok "Q-Cluster reiniciado."
fi

echo ""

# ── Etapa 8: Health Check ─────────────────────────────────────────────────────
log "📋 Etapa 8: Health check..."
sleep 2

rollback_instructions() {
    echo ""
    echo -e "${YELLOW}── Como reverter este deploy ──────────────────────────────────${NC}"
    echo "  1. Restaurar o backup do banco feito na Etapa 3:"
    echo "       ls -t $BACKUPS_DIR | head -1"
    echo "       # sqlite: cp <backup> $PROJECT_DIR/db.sqlite3"
    echo "       # postgresql: pg_restore --clean --if-exists -h 127.0.0.1 -U \$DB_USER -d \$DB_NAME <backup>"
    echo "  2. Voltar o código para a tag do deploy anterior:"
    echo "       git -C $PROJECT_DIR tag -l 'deploy-*' | sort | tail -5"
    echo "       git -C $PROJECT_DIR checkout <tag-anterior>"
    echo "  3. Rodar ./deploy.sh novamente a partir do estado revertido."
    echo -e "${YELLOW}────────────────────────────────────────────────────────────────${NC}"
    echo ""
}

HEALTH_OK=true

# Check Gunicorn
if systemctl is-active --quiet "$GUNICORN_SVC"; then
    ok "Gunicorn está rodando."
else
    warn "Gunicorn não está ativo!"
    HEALTH_OK=false
fi

# Check se a API responde
if curl -sk -o /dev/null -w "%{http_code}" https://pwa.brunonyland.com/api/auth/ | grep -q "200"; then
    ok "API respondendo (200)."
else
    warn "API pode não estar respondendo corretamente."
    HEALTH_OK=false
fi

# Check se o Angular está servindo
if curl -sk -o /dev/null -w "%{http_code}" https://pwa.brunonyland.com/painel/ | grep -q "200"; then
    ok "Angular SPA respondendo (200)."
else
    warn "Angular SPA pode não estar acessível."
    HEALTH_OK=false
fi

if [ "$HEALTH_OK" = false ]; then
    rollback_instructions
    fail "Health check falhou. Deploy considerado com falha — siga as instruções de rollback acima."
fi

echo ""

# ── Etapa 9: Tag de deploy ────────────────────────────────────────────────────
log "📋 Etapa 9: Marcando deploy com git tag..."
DEPLOY_TAG="deploy-$(date +%F-%H%M)"
if git -C "$PROJECT_DIR" tag "$DEPLOY_TAG" 2>&1; then
    ok "Tag criada: $DEPLOY_TAG"
else
    warn "Não foi possível criar a tag $DEPLOY_TAG (talvez já exista) — deploy segue normalmente."
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                   ✅ Deploy Concluído!                      ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  🌐 SPA:  https://pwa.brunonyland.com/painel/              ║"
echo "║  🔌 API:  https://pwa.brunonyland.com/api/                  ║"
echo "║  📖 Docs: https://pwa.brunonyland.com/api/docs/             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
