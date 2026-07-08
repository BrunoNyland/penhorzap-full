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
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
GUNICORN_SVC="gunicorn@pwa.brunonyland.com.service"
QCLUSTER_SVC="penhorzap-qcluster.service"

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

# ── Etapa 1: Testes ────────────────────────────────────────────────────────────
if [ "$SKIP_TESTS" = false ]; then
    log "📋 Etapa 1: Rodando testes da API..."
    cd "$WWW_DIR"

    if DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 "$VENV_PYTHON" manage.py test api -v2 2>&1; then
        ok "Testes da API passaram!"
    else
        fail "Testes da API falharam. Deploy abortado."
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

# ── Etapa 2: Migrations ───────────────────────────────────────────────────────
log "📋 Etapa 2: Verificando migrations pendentes..."
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

# ── Etapa 3: Build Angular ────────────────────────────────────────────────────
log "📋 Etapa 3: Build do Angular SPA..."
cd "$FRONTEND_DIR"

if npx ng build --base-href /painel/ --configuration production 2>&1; then
    ok "Angular build concluído."
else
    fail "Angular build falhou. Deploy abortado."
fi

cd "$PROJECT_DIR"
echo ""

# ── Etapa 4: Collect Static ───────────────────────────────────────────────────
log "📋 Etapa 4: Coletando arquivos estáticos..."
cd "$WWW_DIR"

"$VENV_PYTHON" manage.py collectstatic --noinput 2>&1 | tail -3
ok "Estáticos coletados."

cd "$PROJECT_DIR"
echo ""

# ── Etapa 5: Restart Services ─────────────────────────────────────────────────
log "📋 Etapa 5: Reiniciando serviços..."

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

# ── Etapa 6: Health Check ─────────────────────────────────────────────────────
log "📋 Etapa 6: Health check..."
sleep 2

# Check Gunicorn
if systemctl is-active --quiet "$GUNICORN_SVC"; then
    ok "Gunicorn está rodando."
else
    fail "Gunicorn não está ativo!"
fi

# Check se a API responde
if curl -sk -o /dev/null -w "%{http_code}" https://pwa.brunonyland.com/api/auth/ | grep -q "200"; then
    ok "API respondendo (200)."
else
    warn "API pode não estar respondendo corretamente."
fi

# Check se o Angular está servindo
if curl -sk -o /dev/null -w "%{http_code}" https://pwa.brunonyland.com/painel/ | grep -q "200"; then
    ok "Angular SPA respondendo (200)."
else
    warn "Angular SPA pode não estar acessível."
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
