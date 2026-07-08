# App `api` — API REST de backoffice (operadores humanos)

DRF em `/api/` para o operador humano: consultar as `Solicitacao`s geradas pela
IA, mudar status e fazer upload dos boletos que o sistema reenvia ao cliente.
Swagger em `/api/docs/`, Redoc em `/api/redoc/`, schema em `/api/schema/`.

## Arquivos

| Arquivo | O que faz | Editar quando... |
|---|---|---|
| `views.py` | `SolicitacaoViewSet` (list/retrieve/patch + `@action boletos` que recebe PDFs e dispara `api.tasks.enviar_boletos`). Filtro `?status=`. | quiser mudar o que o operador pode fazer na API, filtros, ou o upload de boleto. |
| `serializers.py` | `SolicitacaoSerializer` (com `historico_mensagens`), `SolicitacaoUpdateSerializer` (só `status`), `BoletoSerializer`, e os `*MiniSerializer`. | quiser mudar o que é exposto no JSON da API. |
| `tasks.py` | `enviar_boletos(solicitacao_id)` — task django-q2: envia intro → PDF → linha digitável → mensagem de acompanhamento (quitação: data de resgate; renovação: próximo vencimento). `_enviar_acompanhamento` decide a mensagem final. | quiser mudar a sequência/mensagens do envio de boleto. |
| `urls.py` | Router: `/api/solicitacoes/`, `/api/schema/`, `/api/docs/`, `/api/redoc/`. | quiser mudar as rotas da API. |
| `models.py` / `admin.py` / `tests.py` | Stubs vazios. | — |

## Quero um comportamento — onde edito?

- Mudar o que o operador vê/faz na API → `views.py`.
- Mudar campos expostos no JSON → `serializers.py`.
- Mudar o **fluxo de envio de boleto** (intro, PDF, linha, acompanhamento) → `tasks.py:enviar_boletos`.
- Mudar a **mensagem pós-boleto** (resgate/próximo vencimento) → `tasks.py:_enviar_acompanhamento` + `core/mensagens_defaults.py`/painel.
- Mudar autenticação/permissões/paginação da API → `penhorzap/settings.py:REST_FRAMEWORK`.

## Gotchas

- Auth: **Token** ou **Session** (staff). Schema/docs só p/ `IsAdminUser`.
- O upload de boleto (`POST /api/solicitacoes/<id>/boletos/`) é assíncrono: dispara `enviar_boletos` no qcluster.
- O acompanhamento usa `Solicitacao.Tipo.QUITAR`/`RENOVAR` + `prazo_dias` e `BotConfig.dias_resgate_garantia`.
- Mudou `tasks.py`? Restart do qcluster.

Veja também: `../core/README.md` (`Solicitacao`/`Boleto`) e `../whatsapp/README.md` (`evolution_client`).
