# penhorzap

Bot de atendimento via WhatsApp com IA para casa de penhores, com painel administrativo completo. O cliente manda mensagem no WhatsApp; se o telefone já está cadastrado, o bot já sabe quem é (sem pedir CPF) e responde com dados do próprio cliente; a IA (Google Gemini) é usada só para **classificar** a intenção (quitar, amortizar, renovar, dúvida) — todo texto enviado ao cliente nasce de templates editáveis, nunca é redigido pela IA — e registra solicitações para o operador enviar os boletos. Fluxo completo: `../docs/fluxo-bot.md`.

## Como funciona

```
Cliente (WhatsApp) ⇄ Evolution API ⇄ webhook Django ⇄ fila (django-q2)
                                                          │
                              telefone cadastrado? identifica na hora, sem CPF, nunca expira
                              senão: pede CPF completo, valida em Python, expira em 24h
                              classifica intenção via Gemini (ia/services.py) -- CLASSIFICADOR PURO
                              responde com template renderizado em Python (nunca texto da IA)
                              + cria Solicitação quando aplicável
                                                          │
                            operador envia boleto (API/painel) → PDF + código de barras no WhatsApp
```

## Apps

| App | Responsabilidade |
|---|---|
| `core` | Models (Cliente, ContratoPenhor, Conversa, Mensagem, Solicitacao, Boleto, FAQ, FAQSugerida, BotConfig, MensagensConfig) e comando de importação de dados |
| `whatsapp` | Webhook da Evolution API, motor do bot (`tasks.py:process_mensagem`), renderer de templates de contrato (`respostas_contrato.py`), cliente HTTP da Evolution, página de conexão via QR code |
| `ia` | Classificação de intenção com Gemini (`extrair_intencao`) — **nunca redige texto ao cliente** —, schema estruturado (Pydantic, `ClassificacaoMensagem`) |
| `api` | API REST (DRF) de backoffice: conversas (com mídia), clientes, FAQs + FAQs sugeridas (curadoria do fallback do bot), solicitações, upload de boletos (PDF + linha digitável). Docs em `/api/docs/` (Swagger) e `/api/redoc/` |
| `painel` | Painel administrativo customizado (staff-only) em `/painel/` |

## Painel (`/painel/`)

- **Estatísticas** — solicitações por tipo/status, volume de mensagens (30 dias), cobertura de clientes, qualidade da IA, boletos, padrões sazonais (dia da semana / faixa do mês), FAQs sugeridas pendentes.
- **Mensagens & Prompt** — edita o prompt do classificador e todos os templates de resposta enviados ao cliente (saudação, contrato, fallback etc.), com restaurar padrão por campo. Glossário completo de placeholders: `../docs/telas.md`.
- **FAQs** — CRUD completo (só FAQs ativas entram no contexto da IA) + aba "Sugestões pendentes": perguntas que o bot não conseguiu responder viram `FAQSugerida`, curadas e aprovadas (vira FAQ real) ou rejeitadas pelo operador.
- **Clientes** — busca, histórico (telefones, contratos, conversas, solicitações) e bloqueio de IA por cliente (lista negra: mensagens são registradas mas o bot não responde).
- **Atendimentos** — histórico de conversas estilo chat (com mídia recebida e enviada, indicador de falha de envio), filtros por estado/revisão humana/tipo de contato; permite responder e anexar arquivo manualmente pelo painel.
- **Simulador IA** — conversa de teste com a IA (com ou sem cliente real no contexto) mostrando a classificação de cada turno (intenção, FAQ, infos de contrato, precisa humano) — a resposta exibida é sempre o template/FAQ renderizado, nunca texto gerado pela IA. Cada mensagem consome uma chamada real ao Gemini.
- **Conexão WhatsApp** — QR code de pareamento da Evolution API e liga/desliga geral do bot.
- **Importar dados** — upload do snapshot SQLite do ERP legado; acompanha status e histórico de importações.

Login usa a autenticação do Django admin (staff); a raiz `/` redireciona para o painel. Detalhe de cada tela (propósito/ações/endpoints): `../docs/telas.md`.

## Stack

- Python 3.12 · Django 5.2 · MySQL (utf8mb4)
- [Evolution API](https://doc.evolution-api.com/) (WhatsApp)
- Google Gemini (`google-genai`, saída estruturada com Pydantic)
- django-q2 (fila assíncrona, broker no próprio MySQL)
- Django REST Framework + drf-spectacular (Swagger)
- gunicorn atrás de nginx; CSS próprio sem dependências de frontend

## Configuração

Variáveis de ambiente (arquivo `.env` no diretório pai do projeto, fora do repositório):

```env
DJANGO_IS_PRODUCTION=1
DJANGO_SECRET_KEY=...
DB_ENGINE=mysql
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=3306
EVOLUTION_API_URL=http://127.0.0.1:8080
EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE=penhorzap
GEMINI_API_KEY=...
WEBHOOK_TOKEN=...   # exigido no webhook /webhook/whatsapp/
```

Sem `GEMINI_API_KEY`, o bot degrada com segurança: registra a mensagem, responde com a mensagem neutra e marca a conversa para revisão humana.

## Rodando

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput

python manage.py runserver        # web
python manage.py qcluster         # fila (processo separado, obrigatório p/ o bot responder)
```

Em produção: gunicorn (via systemd) para o web e um serviço systemd para o `qcluster`. **Mudanças em `whatsapp/tasks.py`, `api/tasks.py` ou `ia/services.py` exigem restart do qcluster** (é ele quem executa essas funções, não o gunicorn).

## Testes

```bash
make test   # raiz do repo -- roda api, core, whatsapp, ia (SQLite, sem HTTPS redirect)
```

Equivalente manual a partir de `www/`:
`DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 python manage.py test api core whatsapp ia -v2`.
CI (`.github/workflows/ci.yml`) roda a mesma suíte + `makemigrations --check --dry-run` a cada push/PR.

## API de backoffice

Autenticação por token DRF ou sessão. Documentação interativa em `/api/docs/` (staff).

```bash
# listar solicitações pendentes
GET /api/solicitacoes/?status=pendente

# atualizar status
PATCH /api/solicitacoes/<id>/   {"status": "concluida"}

# enviar boletos (multipart; linha_digitavel opcional, pareada por índice com os arquivos)
POST /api/solicitacoes/<id>/boletos/
  arquivo=<pdf1> arquivo=<pdf2>
  linha_digitavel=<código1> linha_digitavel=<código2>
```

O upload dispara o envio assíncrono ao WhatsApp do cliente: texto de introdução → PDF → linha digitável em mensagem separada (para copiar e colar).
