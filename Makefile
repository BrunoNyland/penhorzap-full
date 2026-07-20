#!/usr/bin/env bash
# =============================================================================
# PenhorZap — Makefile para CI, build e deploy
# =============================================================================
# Uso:
#   make test          — roda testes da API (backend)
#   make test-int      — roda testes de integração
#   make build         — build do Angular SPA
#   make deploy        — build + collect static + restart
#   make lint          — verificações básicas
#   make all           — test + build + deploy
# =============================================================================

.PHONY: help test test-int build deploy restart lint all clean

# Prepend local Node 24 bin to PATH for Angular 22 compatibility
export PATH := /var/www/pwa.brunonyland.com/node-v24.15.0-linux-x64/bin:$(PATH)

# ── Variáveis ──────────────────────────────────────────────────────────────────
VENV         := /var/www/pwa.brunonyland.com/venv/bin
PYTHON       := $(VENV)/python
PIP          := $(VENV)/pip
MANAGE       := cd www && $(PYTHON) manage.py
NPX          := npx
FRONTEND_DIR := frontend
DIST_DIR     := $(FRONTEND_DIR)/dist/frontend/browser
GUNICORN_SVC := gunicorn@pwa.brunonyland.com.service

# Variáveis de ambiente para testes (SQLite in-memory, sem HTTPS redirect)
TEST_ENV     := DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0

help: ## Mostra esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ── Testes ─────────────────────────────────────────────────────────────────────
test: ## Roda testes unitários (api, core, whatsapp, ia)
	cd www && $(TEST_ENV) $(PYTHON) manage.py test api core whatsapp ia -v2

test-int: ## Roda testes de integração (API + SPA + Nginx)
	cd www && $(TEST_ENV) $(PYTHON) manage.py test api.tests_integration -v2

test-all: test test-int ## Roda todos os testes

# ── Lint / Checks ──────────────────────────────────────────────────────────────
lint: ## Verificações básicas de integridade
	@echo "🔍 Verificando linting Python (Ruff)..."
	$(VENV)/ruff check www
	@echo ""
	@echo "🔍 Verificando importações Django..."
	cd www && $(TEST_ENV) $(PYTHON) manage.py check --deploy 2>&1 | grep -v "^$$" || true
	@echo ""
	@echo "🔍 Verificando migrations pendentes..."
	cd www && $(TEST_ENV) $(PYTHON) manage.py makemigrations --check --dry-run 2>&1 || true
	@echo ""
	@echo "🔍 Verificando Angular build..."
	cd $(FRONTEND_DIR) && $(NPX) ng build --configuration production 2>&1 | tail -5
	@echo ""
	@echo "🔍 Verificando configuração Nginx..."
	nginx -t 2>&1
	@echo ""
	@echo "✅ Lint completo."

# ── Build ──────────────────────────────────────────────────────────────────────
build: ## Build do Angular SPA (produção)
	@echo "🔨 Building Angular SPA..."
	cd $(FRONTEND_DIR) && $(NPX) ng build --base-href /painel/ --configuration production
	@echo "✅ Angular build concluído: $(DIST_DIR)/"

# ── Deploy ─────────────────────────────────────────────────────────────────────
deploy: build ## Build + collect static + restart serviços
	@echo "📦 Coletando arquivos estáticos do Django..."
	$(MANAGE) collectstatic --noinput
	@echo ""
	@echo "🔄 Reiniciando Gunicorn..."
	systemctl restart $(GUNICORN_SVC)
	@echo ""
	@echo "🔄 Recarregando Nginx..."
	nginx -t && systemctl reload nginx
	@echo ""
	@echo "✅ Deploy concluído!"

restart: ## Reinicia Gunicorn + Nginx sem rebuild
	systemctl restart $(GUNICORN_SVC)
	systemctl reload nginx
	@echo "✅ Serviços reiniciados."

# ── Migrations ─────────────────────────────────────────────────────────────────
migrate: ## Aplica migrations pendentes
	$(MANAGE) migrate
	@echo "✅ Migrations aplicadas."

makemigrations: ## Gera novas migrations
	$(MANAGE) makemigrations
	@echo "✅ Migrations geradas."

# ── Clean ──────────────────────────────────────────────────────────────────────
clean: ## Remove build artifacts
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/.angular/cache
	@echo "✅ Build artifacts removidos."

# ── Atalhos ────────────────────────────────────────────────────────────────────
all: test build deploy ## Roda testes, build e deploy
