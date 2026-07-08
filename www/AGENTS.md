# AGENTS.md

Bot de WhatsApp com IA (Google Gemini) para casa de penhores. Django 5.2 + MySQL + django-q2 + Evolution API. UI e prompts em pt-BR; `TIME_ZONE = America/Sao_Paulo`.

## Layout (não óbvio)

O repo vive em `www/`, mas o **runtime root** é o diretório pai (`PROJECT_ROOT = BASE_DIR.parent`, ver `penhorzap/settings.py:13`). Tudo isso vive fora do repo e é gitignored:

- `.env` — carregado pelo `manage.py`, `wsgi.py` e `settings.py` a partir de `PROJECT_ROOT / ".env"`. **Não procure `.env` dentro de `www/`.**
- `venv/` — Python 3.12. Ative com `source ../venv/bin/activate` a partir de `www/`.
- `staticfiles/` (saída do `collectstatic`), `media/` (uploads de boletos), `db.sqlite3` (quando não usa MySQL).

Irmão ao repo: `../evolution/docker-compose.yml` sobe a Evolution API (Postgres + `evoapicloud/evolution-api:v2.3.7`) em `127.0.0.1:8080`, com webhook global apontando para `https://pwa.brunonyland.com/webhook/whatsapp/`.

## Comandos

Rode tudo a partir de `www/` com o venv ativo:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
python manage.py runserver          # web
python manage.py qcluster           # fila — processo separado, obrigatório p/ o bot responder
python manage.py import_sqlite <caminho_para_0886.sqlite3>   # import legado (idempotente, bulk upsert)
```

DB engine é env-driven: `DB_ENGINE=mysql` usa MySQL (utf8mb4); qualquer outro valor cai em SQLite em `PROJECT_ROOT/db.sqlite3`.

Não há lint, typecheck, formatter, pytest, tox ou CI configurados. Os `*/tests.py` são stubs vazios — não existe suite de testes a rodar.

## Modelo de dois processos (gotcha crítico)

O `qcluster` executa as tasks; o gunicorn/runserver só servem HTTP. **Mudanças em `whatsapp/tasks.py`, `api/tasks.py` ou `ia/services.py` exigem restart do qcluster** — o processo web não recarrega esse código. Em produção: gunicorn (systemd) + qcluster (systemd) separados.

## Apps

| App | Responsabilidade |
|---|---|
| `core` | Models (`Cliente`, `ContratoPenhor`, `Conversa`, `Mensagem`, `Solicitacao`, `Boleto`, `FAQ`, `BotConfig`, `MensagensConfig`, `Telefone`, `AgenciaPenhor`, `Licitacao`), `mensagens_defaults.py`, comando `import_sqlite`, `utils.py` (normalização de telefone BR etc.) |
| `whatsapp` | Webhook da Evolution, `tasks.py:process_mensagem` (task principal), `evolution_client.py`, página de QR code |
| `ia` | `services.py:extrair_intencao` (Gemini), `schemas.py` (Pydantic) |
| `api` | DRF de backoffice em `/api/` (Swagger em `/api/docs/`, Redoc em `/api/redoc/`); `tasks.py:enviar_boletos` |
| `painel` | Admin customizado staff-only em `/painel/`; raiz `/` redireciona para o dashboard |

Login (painel e API) usa a auth do Django admin (staff). Template de login admin customizado em `templates/admin/login_penhorzap.html`.

## Invariantes (não quebre)

- **`ia.services.extrair_intencao` nunca levanta.** Sem `GEMINI_API_KEY`, SDK ausente ou erro do Gemini → fallback neutro com `precisa_humano=True`. Import de `core.models` dentro de `_config_textos` é intencional, p/ proteger o app registry.
- **Webhook sempre ack 200.** `whatsapp/views.py:whatsapp_webhook` retorna 200 mesmo em exceção. Rejeita payloads sem `X-Webhook-Token` (env `WEBHOOK_TOKEN`). Captura `pushName` em `Mensagem.push_name`.
- **Dedup** por `wa_message_id`; `fromMe` e grupos `@g.us` são ignorados.
- **Garantias duras de privacidade/segurança no `whatsapp/tasks.py:process_mensagem` (em Python, não na IA):**
  - **CPF validado em Python** (`core.utils.validar_cpf`) — checksum oficial. A IA **não** decide validade.
  - **Contratos só chegam à IA se `cpf_verificado` E `database_atualizada`** (`_contratos_ativos_values`). Fora disso a IA recebe lista vazia → não pode vazar dados de terceiros, desatualizados ou liquidados.
  - **Só contratos ativos** (exclui `situacao_codigo` em `{LQ,LQVL,LQDE,SJLQ,LQSD}` e `situacao` contendo "Liquidado").
  - **Só campos permitidos** passam à IA: `contrato`, `data_vencimento`, `vlr_emprestimo` (valor do contrato), `vlr_liquido` (valor de quitação — **mapeamento presumido, confirmar**), `vlr_renovacao_30..180`, `parcelado`, `vlr_parcela`. Nunca aniversário/telefone/endereço.
  - **A IA nunca calcula valores** — só cita literais dos contratos fornecidos.
- **Identidade**: o cliente digita o CPF **completo** (não mais 3 dígitos); deve ser válido E bater com o `cliente.cpf` do contato (Telefone ou nome salvo `PHN_CPF_NOME`). Verificação expira em 24h (`VERIFICACAO_VALIDADE`).
- **Triagem de contato** (`_classificar_contato`): `ContatoSalvo` (sync da agenda, `PHN_CPF_NOME`=cliente) > `Telefone` (match por número) > `pushName`. Pessoal → ignora; desconhecido sem resposta prévia → saúda (se `BotConfig.responder_desconhecidos`).
- **Singletons**: `BotConfig.get_solo()` (ativo, freshness, horário de encerramento, etc.) e `MensagensConfig.get_solo()` — sempre via `get_solo()`; defaults em `core/mensagens_defaults.py`.
- **Cliente bloqueado** (`cliente.bloqueado_ia`) → registra, não responde, marca p/ revisão.

## Fluxo principal

Ativação (`toggle_bot` em `whatsapp/views.py`) → enfileira `sincronizar_contatos` + `processar_nao_lidas` (replay, do nosso DB, das IN não atendidas nas últimas 24h — não depende da Evolution para "unread").

Por mensagem (`process_mensagem`): classifica contato → pessoal ignora / desconhecido saúda / cliente segue → CPF digitado? valida em Python, bate com cadastro → marca `cpf_verificado` → chama `extrair_intencao` (Gemini, schema Pydantic em `ia/schemas.py`) com ESTADO (cpf_verificado, database_atualizada, contato_tipo) e contratos ativos filtrados → gates pós-IA (exige CPF p/ info específica/pagamento/segunda via; exige DB fresca p/ info específica/pagamento) → `PAGAMENTO` pronto? cria uma `Solicitacao` por draft (tipo + prazo + contratos; contratos vazio = todos os ativos) → `SEGUNDA_VIA`? clona última solicitação com boleto do dia anterior e pede confirmação → responde.

Boleto: operador faz `POST /api/solicitacoes/<id>/boletos/` (PDF + linha digitável) → `api.tasks.enviar_boletos` envia intro → PDF → linha digitável → mensagem pós-boleto (quitação: data de resgate `hoje + dias_resgate_garantia`; renovação: próximo vencimento `hoje + prazo_dias`).

Encerramento: `Schedule` django-q2 cron `*/5 * * * *` → `verificar_encerramento` desliga o bot a partir de `BotConfig.horario_encerramento`, uma vez por dia (`ultimo_encerramento_auto`); permite reativar à mão depois.

Sem `GEMINI_API_KEY` o bot degrada com segurança (registra, responde neutro, marca p/ revisão humana).

## Pontos a confirmar com o dono (implementados como presumido)

- **`valor de quitação`** mapeado para `vlr_liquido` — confirmar se é o campo certo do ERP legado.
- **Endpoint de contatos** (`fetch_contacts`) presume Evolution v2 (`/chat/findContacts/{instance}`, overridável via `EVOLUTION_CONTACTS_PATH`); se 404, a sync falha em silêncio e a triagem cai no fallback Telefone/pushName. Validar contra a instância v2.3.7 ao vivo.
- **Freshness** default 24h (`BotConfig.freshness_horas`), ajustável no painel; `import_sqlite` carimba `ultima_atualizacao_dados`.
