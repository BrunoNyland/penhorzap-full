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

Não há lint/typecheck/formatter além do `manage.py check --deploy`. Há suite
de testes real (`api`, `core`, `whatsapp`, `ia`) — rode com `make test`
(raiz do repo) ou `DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0 python manage.py
test api core whatsapp ia -v2` a partir de `www/`; CI em
`.github/workflows/ci.yml` roda a mesma suíte (+ `makemigrations --check`) a
cada push/PR. `docs/telas.md` e `docs/fluxo-bot.md` (raiz do repo)
documentam as telas do painel e o fluxo do bot passo a passo.

## Modelo de dois processos (gotcha crítico)

O `qcluster` executa as tasks; o gunicorn/runserver só servem HTTP. **Mudanças em `whatsapp/tasks.py`, `api/tasks.py` ou `ia/services.py` exigem restart do qcluster** — o processo web não recarrega esse código. Em produção: gunicorn (systemd) + qcluster (systemd) separados.

## Apps

| App | Responsabilidade |
|---|---|
| `core` | Models (`Cliente`, `ContratoPenhor`, `Conversa`, `Mensagem`, `Solicitacao`, `Boleto`, `FAQ`, `BotConfig`, `MensagensConfig`, `Telefone`, `AgenciaPenhor`, `Licitacao`), `mensagens_defaults.py`, comando `import_sqlite`, `utils.py` (normalização de telefone BR etc.) |
| `whatsapp` | Webhook da Evolution (`views.py:whatsapp_webhook`, `_extrair_conteudo`), `tasks.py:process_mensagem` (task principal, motor do bot), `respostas_contrato.py` (renderer determinístico dos templates de contrato), `evolution_client.py`, página de QR code |
| `ia` | `services.py:extrair_intencao` (Gemini, classificador puro — nunca redige texto), `schemas.py` (`ClassificacaoMensagem`, Pydantic) |
| `api` | DRF de backoffice em `/api/` (Swagger em `/api/docs/`, Redoc em `/api/redoc/`); `tasks.py:enviar_boletos`; `FAQSugeridaViewSet` (curadoria do fallback do bot), `ConversaViewSet.enviar_arquivo` (anexo do operador) |
| `painel` | Admin customizado staff-only em `/painel/`; raiz `/` redireciona para o dashboard |

Login (painel e API) usa a auth do Django admin (staff). Template de login admin customizado em `templates/admin/login_penhorzap.html`.

## Invariantes (não quebre)

- **`ia.services.extrair_intencao` nunca levanta.** Sem `GEMINI_API_KEY`, SDK ausente ou erro do Gemini → fallback neutro com `precisa_humano=True`. Import de `core.models` dentro de `_config_textos` é intencional, p/ proteger o app registry.
- **Webhook sempre ack 200.** `whatsapp/views.py:whatsapp_webhook` retorna 200 mesmo em exceção. Rejeita payloads sem `X-Webhook-Token` (env `WEBHOOK_TOKEN`). Captura `pushName` em `Mensagem.push_name`.
- **Dedup** por `wa_message_id`; `fromMe` e grupos `@g.us` são ignorados.
- **A IA (Gemini) é um CLASSIFICADOR PURO — nunca redige texto ao cliente.**
  Ela só preenche `ia.schemas.ClassificacaoMensagem` (JSON estruturado); todo
  texto enviado nasce de templates (`core.models.MensagensConfig`, campos
  `msg_*`/`tpl_*`, editáveis em `/config`, defaults em
  `core/mensagens_defaults.py`) renderizados em Python por
  `whatsapp/respostas_contrato.py:render_template`/`renderizar_infos_contrato`.
  Fluxo completo, schema e glossário de placeholders: ver
  `../docs/fluxo-bot.md` e `../docs/telas.md` (raiz do repo).
- **Garantias duras de privacidade/segurança no `whatsapp/tasks.py:process_mensagem` (em Python, não na IA):**
  - **CPF validado em Python** (`core.utils.validar_cpf`) — checksum oficial. A IA **não** decide validade.
  - **Contratos só chegam à IA se identificado (telefone OU CPF) E `database_atualizada`** (`_contratos_ativos_values`). Fora disso a IA recebe lista vazia → não pode vazar dados de terceiros, desatualizados ou liquidados.
  - **Só contratos ativos** (exclui `situacao_codigo` em `{LQ,LQVL,LQDE,SJLQ,LQSD}` e `situacao` contendo "Liquidado").
  - **Nenhum valor financeiro chega ao prompt** (`ia.services._formatar_contratos`): a IA só vê `contrato`, `data_vencimento`, `parcelado` — o suficiente para desambiguar, nunca para redigir/calcular um valor. Os valores (`vlr_emprestimo`, `vlr_liquido` — valor de quitação, **mapeamento presumido, confirmar** —, `vlr_renovacao_30..180`, `vlr_parcela`) só existem no renderer Python (`respostas_contrato.py`), lidos do banco na hora de montar a resposta. Nunca aniversário/telefone/endereço em nenhum dos dois caminhos.
  - **FAQs no prompt**: só `id`+`pergunta`, nunca o texto das respostas.
- **Identidade — dois caminhos, não intercambiáveis** (`Conversa.identificacao`):
  - **Telefone cadastrado** (`Telefone` bate com o `remoteJid`) → `identificacao=telefone` **imediatamente, sem pedir CPF, e nunca expira**. Primeira interação responde com `tpl_saudacao_cliente` (nome do cliente) e encerra o turno sem chamar a IA.
  - **CPF digitado** (contato sem telefone cadastrado) → precisa ser válido E bater com o `cliente.cpf` do contato, se já havia um (Telefone ou nome salvo `PHN_CPF_NOME`) → `identificacao=cpf`. **Só este caminho expira**, em 24h (`VERIFICACAO_VALIDADE`).
  - CPF formatado (`.`/`-`) é reconhecido em qualquer estado da conversa; 11 dígitos **crus** só contam como CPF quando `conv.estado == aguardando_verificacao` (evita falso positivo de telefone/número de contrato virar CPF).
  - **Desconhecido identificado só por CPF** (nunca por telefone salvo) pedindo `info_contrato` → `msg_info_negada_desconhecido` (só o boleto tem os dados; pagamento continua permitido).
- **Triagem de contato** (`_classificar_contato`): `Telefone` (match por número, com/sem 9º dígito) > `ContatoSalvo` (sync da agenda, `PHN_CPF_NOME`=cliente) > `pushName`. Pessoal → ignora; desconhecido sem resposta prévia → saúda (se `BotConfig.responder_desconhecidos`).
- **`Mensagem.enviado_ok`**: toda resposta OUT persiste o resultado real do
  envio (`EvolutionClient.send_text`/`send_file`) — `False` marca
  `Conversa.precisa_revisao_humana=True` em vez de falhar silenciosamente. O
  painel (`/conversations`) mostra um indicador de falha quando
  `enviado_ok === false`.
- **Lock/coalescência por conversa** (`Conversa.processando_desde`): mutex
  leve (janela curta, não segura durante a chamada à IA/Evolution) evita
  duas tasks processando a mesma conversa ao mesmo tempo; se ocupado,
  reagenda via `django_q.tasks.schedule`. Se já existe uma `Mensagem` IN
  mais nova na conversa, a task mais antiga aborta sem responder
  (coalescência).
- **Singletons**: `BotConfig.get_solo()` (ativo, freshness, horário de encerramento, etc.) e `MensagensConfig.get_solo()` — sempre via `get_solo()`; defaults em `core/mensagens_defaults.py`.
- **Cliente bloqueado** (`cliente.bloqueado_ia`) → registra, não responde, marca p/ revisão.

## Fluxo principal

Ativação (`toggle_bot` em `whatsapp/views.py`) → enfileira `sincronizar_contatos` + `processar_nao_lidas` (replay, do nosso DB, das IN não atendidas nas últimas 24h — não depende da Evolution para "unread").

Por mensagem (`process_mensagem`, mutex por conversa no início): classifica
contato → pessoal ignora / desconhecido sem resposta prévia saúda / telefone
cadastrado identifica na hora e, na primeira interação, responde
`tpl_saudacao_cliente` e encerra o turno (sem IA) → mídia sem texto pede
para escrever (sem IA) → CPF digitado? valida em Python, bate com cadastro
→ marca `identificacao=cpf` (expira em 24h; telefone nunca expira) → chama
`extrair_intencao` (Gemini, **classificador puro**, schema
`ClassificacaoMensagem` em `ia/schemas.py`) com ESTADO (identificado,
database_atualizada, contato_tipo) e contratos ativos **sem valores
financeiros** → gates pós-IA em Python (exige identificação p/
info_contrato/pagamento/segunda_via; exige DB fresca p/
info_contrato/pagamento; desconhecido identificado só por CPF pedindo
info_contrato → só boleto) → `info_contrato`? renderiza template
determinístico com valores do banco (`whatsapp/respostas_contrato.py`) →
`pagamento` pronto? cria uma `Solicitacao` por draft (tipo + prazo +
contratos; contratos vazio = todos os ativos) → `segunda_via`? clona última
solicitação com boleto do dia anterior e pede confirmação → `faq_id`?
responde as `FAQResposta` em ordem → nada casou (`duvida_geral` sem FAQ,
`outro`)? cria/incrementa `FAQSugerida` de curadoria (`/faqs`, aba
"Sugestões pendentes") e marca revisão humana → responde (grava
`Mensagem.enviado_ok` sempre). Passo a passo completo:
`../docs/fluxo-bot.md`.

Boleto: operador faz `POST /api/solicitacoes/<id>/boletos/` (PDF + linha digitável) → `api.tasks.enviar_boletos` envia intro → PDF → linha digitável → mensagem pós-boleto (quitação: data de resgate `hoje + dias_resgate_garantia`; renovação: próximo vencimento `hoje + prazo_dias`).

Encerramento: `Schedule` django-q2 cron `*/5 * * * *` → `verificar_encerramento` desliga o bot a partir de `BotConfig.horario_encerramento`, uma vez por dia (`ultimo_encerramento_auto`); permite reativar à mão depois.

Sem `GEMINI_API_KEY` o bot degrada com segurança (registra, responde neutro, marca p/ revisão humana).

## Pontos a confirmar com o dono (implementados como presumido)

- **`valor de quitação`** mapeado para `vlr_liquido` — confirmar se é o campo certo do ERP legado.
- **Endpoint de contatos** (`fetch_contacts`) presume Evolution v2 (`/chat/findContacts/{instance}`, overridável via `EVOLUTION_CONTACTS_PATH`); se 404, a sync falha em silêncio e a triagem cai no fallback Telefone/pushName. Validar contra a instância v2.3.7 ao vivo.
- **Freshness** default 24h (`BotConfig.freshness_horas`), ajustável no painel; `import_sqlite` carimba `ultima_atualizacao_dados`.
