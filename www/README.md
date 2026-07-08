# penhorzap

Bot de atendimento via WhatsApp com IA para casa de penhores, com painel administrativo completo. O cliente manda mensagem no WhatsApp, a IA (Google Gemini) entende a intenção (quitar, amortizar, renovar, dúvida), responde em nome do dono — em primeira pessoa, sem nunca revelar ser um bot — e registra solicitações para o operador enviar os boletos.

## Como funciona

```
Cliente (WhatsApp) ⇄ Evolution API ⇄ webhook Django ⇄ fila (django-q2)
                                                          │
                                          identifica cliente pelo telefone
                                          verifica identidade (3 últimos dígitos do CPF)
                                          extrai intenção via Gemini (ia/services.py)
                                          responde + cria Solicitação
                                                          │
                            operador envia boleto (API/painel) → PDF + código de barras no WhatsApp
```

## Apps

| App | Responsabilidade |
|---|---|
| `core` | Models (Cliente, ContratoPenhor, Conversa, Mensagem, Solicitacao, Boleto, FAQ, BotConfig, MensagensConfig) e comando de importação de dados |
| `whatsapp` | Webhook da Evolution API, pipeline de processamento de mensagens (`tasks.py`), cliente HTTP da Evolution, página de conexão via QR code |
| `ia` | Extração de intenção com Gemini (`extrair_intencao`), schema estruturado (Pydantic), prompt com persona em 1ª pessoa |
| `api` | API REST (DRF) de backoffice: consultar solicitações, atualizar status, upload de boletos (PDF + linha digitável). Docs em `/api/docs/` (Swagger) e `/api/redoc/` |
| `painel` | Painel administrativo customizado (staff-only) em `/painel/` |

## Painel (`/painel/`)

- **Estatísticas** — solicitações por tipo/status, volume de mensagens (30 dias), cobertura de clientes, qualidade da IA, boletos, padrões sazonais (dia da semana / faixa do mês).
- **Mensagens & Prompt** — edita o prompt do Gemini e todas as mensagens fixas enviadas ao cliente, com restaurar padrão por campo.
- **FAQs** — CRUD completo; só FAQs ativas entram no contexto da IA.
- **Clientes** — busca, histórico (telefones, contratos, conversas, solicitações) e bloqueio de IA por cliente (lista negra: mensagens são registradas mas o bot não responde).
- **Atendimentos** — histórico de conversas estilo chat, filtros por estado/revisão humana.
- **Simulador IA** — conversa de teste com a IA (com ou sem cliente real no contexto) mostrando a classificação de cada resposta (intenção, escopo, precisa humano) — sem tocar nos dados reais nem enviar WhatsApp. Cada mensagem consome uma chamada real ao Gemini.
- **Conexão WhatsApp** — QR code de pareamento da Evolution API e liga/desliga geral do bot.

Login usa a autenticação do Django admin (staff); a raiz `/` redireciona para o painel.

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
