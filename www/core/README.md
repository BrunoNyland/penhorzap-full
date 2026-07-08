# App `core` — models, dados e regras de domínio

O `core` é o "coração de dados" do penhorzap: todos os models, os textos/prompt
padrão, a validação de CPF/telefone e o importador do banco legado. Os outros
apps (`whatsapp`, `ia`, `api`, `painel`) dependem deste — se mudou um model
aqui, rode `makemigrations core` + `migrate`.

## Arquivos

| Arquivo | O que faz | Editar quando... |
|---|---|---|
| `models.py` | Todos os models. Singletons `BotConfig`/`MensagensConfig` via `get_solo()`. `Cliente`, `ContratoPenhor`, `Conversa` (`tipo_contato`, `cpf_verificado`, `slots`, `nome_salvo`), `Mensagem` (`push_name`), `Solicitacao` (`Tipo`: quitar/renovar/parcela/segunda_via + `prazo_dias`), `Boleto`, `FAQ`, `Telefone`, `ContatoSalvo`, `AgenciaPenhor`, `Licitacao`. `BotConfig.database_atualizada()` é o gate de freshness. | quiser mudar um campo, regra de status, default, ou o limiar de freshness. |
| `utils.py` | `validar_cpf` (checksum oficial), `normalizar_cpf`, `parse_nome_salvo` (convenção `PHN_CPF_NOME`), normalização de telefone BR. | quiser mudar a validação de CPF ou a detecção de contato pelo nome salvo. |
| `mensagens_defaults.py` | Fonte única de todos os textos padrão e do **system prompt** do Gemini. Sobrescrevível em produção pelo `MensagensConfig` (painel). | quiser mudar um default de mensagem/prompt (mas em prod, edite via painel). |
| `admin.py` | Registra todos os models no `/admin/`. `BotConfig`/`MensagensConfig` impedem add/delete p/ forçar singleton. | quiser expor/ocultar um model no admin, mudar `list_display`/filtros. |
| `management/commands/import_sqlite.py` | Importa o `.sqlite3` legado (idempotente, bulk upsert). Carimba `BotConfig.ultima_atualizacao_dados` (freshness). | quiser mudar como o dado legado entra ou o mapeamento de campos. |
| `migrations/` | Estado do schema (`0001`–`0007`; a `0007` cria o `Schedule` do django-q2 p/ o encerramento automático). | nunca edite à mão; use `makemigrations`/`migrate`. |
| `views.py` / `tests.py` / `apps.py` | Stubs vazios. | — |

## Quero um comportamento — onde edito?

- Mudar textos das mensagens ou o prompt → `mensagens_defaults.py` (defaults) **ou** tela **Mensagens & Prompt** do painel (sobrescreve em prod).
- Mudar regra de validação de CPF → `utils.py:validar_cpf`.
- Mudar como o nome salvo `PHN_CPF_NOME` é interpretado → `utils.py:parse_nome_salvo`.
- Mudar limiar de "database desatualizada" (freshness) / horário de encerramento / dias de resgate → `models.py:BotConfig` (e o painel `/painel/bot/`).
- Mudar **quais campos de contrato a IA pode ver** → não aqui; é o gate em `whatsapp/tasks.py:_contratos_ativos_values`.
- Mudar o import do legado / mapeamento de campos → `management/commands/import_sqlite.py`.
- Exibir um model novo no admin → `admin.py`.

## Gotchas

- Singletons: **sempre** `BotConfig.get_solo()` / `MensagensConfig.get_solo()` — nunca `.objects.first()`.
- Mudou `models.py`? `python manage.py makemigrations core && python manage.py migrate`.
- O repo vive em `www/`, mas `.env`/`venv`/`db.sqlite3`/`staticfiles`/`media` estão no diretório pai (`PROJECT_ROOT`).

Veja também: `../AGENTS.md` (invariantes e fluxo) e `../README.md` (visão geral).
