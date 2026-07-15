# PenhorZap v2 — Plano de Produção (bot determinístico + mídia + responsivo + CI)

## Contexto

O PenhorZap (Django 5.2 + django-q2 + Evolution API + Gemini em `www/`, Angular 19 em `frontend/`) funciona, mas: (1) exige CPF mesmo de telefones já cadastrados; (2) a Gemini **redige** as respostas com valores de contratos (risco + tokens caros — ~1.900–2.700 tokens de input/chamada); (3) o painel não exibe mídia recebida (bug de wiring: `ConversaDetailSerializer.get_mensagens` em `api/serializers.py:322` usa `MensagemMiniSerializer` sem os campos de mídia que o frontend já consome; `MensagemSerializer` completo é código morto) nem permite enviar arquivos; (4) só o app `api` tem testes, não há CI, e faltam itens de hardening (SECRET_KEY com fallback, sem HSTS, sem backup pré-migrate, bugs de concorrência documentados em `www/MELHORIAS.md`).

**Decisões do dono (confirmadas):**
- **Telefone cadastrado = identificado** (sem CPF, sem expiração). Bot cumprimenta pelo nome e pergunta como pode ajudar. Só dados do titular do telefone.
- **Desconhecidos**: pedem CPF completo; mesmo verificados, recebem apenas boleto — nenhum dado além do que consta no próprio boleto.
- **Gemini = classificador puro**: nunca escreve texto ao cliente. FAQs já são determinísticas (id+pergunta no prompt, resposta do banco); contratos passam a usar templates configuráveis; fallback = mensagem padrão + **sugestão de FAQ pendente de aprovação** + marca revisão.
- **CI apenas validação** (sem deploy automático).

**⚠️ Dia zero (antes de tudo): token GitHub `gho_…` exposto na URL do remote em `.git/config` — revogar no GitHub e `git remote set-url origin git@github.com:BrunoNyland/penhorzap-full.git` (ou PAT via credential helper).** Conferir `git grep gho_ $(git rev-list --all)` por precaução (esperado: só em `.git/config`, não versionado).

---

## Fase 0 — Contrato compartilhado (bloqueante, mergear antes dos workstreams)

Concentra TODAS as mudanças de models/migrações/schema num único merge para eliminar conflitos entre agentes.

### `www/core/models.py`
- **`Conversa`** (linha ~250): novo campo `identificacao` (choices: `nenhum|telefone|cpf`, default `nenhum`) e `processando_desde` (DateTimeField null — mutex leve por conversa). `cpf_verificado`/`verified_at` continuam, mas só valem para o caminho CPF; expiração de 24h só quando `identificacao == "cpf"`.
- **`Mensagem`** (linha ~287): `tipo_midia` (choices `image|audio|video|document|""`), `arquivo` (FileField `upload_to="conversa_arquivos/%Y/%m/"` — anexos OUT do operador), `enviado_ok` (BooleanField null — corrige MELHORIAS #9 mantendo auditoria).
- **Novo model `FAQSugerida`**: `pergunta`, `pergunta_original`, FK `conversa` (SET_NULL), `ocorrencias` (dedup: pergunta igual pendente → incrementa), `status` (`pendente|aprovada|rejeitada`), FK `faq_criada`, `revisado_por/em`, `criado_em`. Ordering `-ocorrencias, -criado_em`.
- **`MensagensConfig`** (linha ~386) + defaults em `core/mensagens_defaults.py`: novos templates (mesmo padrão `msg_*`, reaproveita restore por campo de `api/views.py:470`):
  - `tpl_saudacao_cliente` (`{saudacao}`, `{nome}`), `tpl_contrato_vencimento`, `tpl_contrato_renovacao` (`{contrato}`, `{prazo_dias}`, `{valor_renovacao}`, `{vencimento}`), `tpl_contrato_quitacao`, `tpl_contrato_parcela`, `tpl_contrato_resumo`, `tpl_lista_header`/`tpl_lista_footer`, `msg_fallback_sem_resposta`, `msg_info_negada_desconhecido`, `msg_midia_nao_suportada`.

### `www/ia/schemas.py` — novo schema de saída
`ClassificacaoMensagem`: `tipo_intencao` (`saudacao|duvida_geral|info_contrato|pagamento|segunda_via|outro`), `faq_id`, `infos_contrato: List[InfoContratoPedido]` (`info`: `vencimento|valor_renovacao|valor_quitacao|valor_parcela|lista_contratos|detalhe_contrato`; `contratos: List[str]` vazio=todos; `prazo_dias` opcional), `solicitacoes` (mantém `SolicitacaoDraft`), `pronto_para_criar_solicitacao`, `precisa_humano`, `pergunta_sugerida_faq` (pergunta reescrita curta quando dúvida geral sem FAQ). **Removidos: `resposta_sugerida`, `cpf_extraido`, `duvida_cliente`, `resposta_faq`.**

### Migração
`core/migrations/00XX_v2_models.py` com `RunPython` de backfill: `Mensagem.tipo_midia` a partir de `payload_bruto`; `Conversa.identificacao="cpf"` onde `cpf_verificado` preenchido.

---

## WS-A — Motor do bot (depende de F0)

**Arquivos (proprietário exclusivo):** `www/whatsapp/tasks.py`, novo `www/whatsapp/respostas_contrato.py`, `www/ia/services.py`, `core/mensagens_defaults.py` (system prompt), `api/views.py` **somente** `SimulatorChatAPIView`.

1. **Prompt enxuto** (`ia/services.py`):
   - Novo `DEFAULT_SYSTEM_PROMPT` (~400 tokens vs ~1.900): só instruções de classificação, sem persona/regras de redação (rascunho no relatório do arquiteto — regras: nunca inventar contrato, `precisa_humano` em insistência/irritação, dúvida que depende de dados do cliente = `info_contrato`).
   - `_formatar_contratos`: **remover valores financeiros** — só `contrato=N vencimento=D parcelado=s/n` (a IA só precisa desambiguar). FAQs continuam id+pergunta.
   - Manter invariante: `extrair_intencao` nunca levanta; fallback neutro `precisa_humano=True`.
   - Resultado esperado: ~800–1.100 tokens input (−60%), output só JSON de rótulos (−70%); system prompt fixo curto ativa implicit caching do Gemini.
2. **Novo `respostas_contrato.py`**: `formatar_moeda`/`formatar_data` pt-BR; `render_template` tolerante (`format_map` + SafeDict — placeholder errado no painel não explode, loga warning); `renderizar_infos_contrato(cliente, pedidos, msgs)` — resolve `pedido.contratos ∩ ativos` (reutiliza `_contratos_ativos_values`, valores **do banco**, nunca da IA), `prazo_dias` ausente → 30 com nota, multi-contrato com header/footer, sem ativos → `msg_sem_contratos_ativos`.
3. **`process_mensagem` redesenhado** (`tasks.py:312-513`):
   - **Lock por conversa** (MELHORIAS #1): `select_for_update` só na aquisição do mutex `processando_desde` (janela curta, não segura lock durante Gemini); se em andamento <60s, re-enfileira. **Coalescência**: se existe IN mais novo, aborta (a task mais nova responde). `finally` limpa o mutex.
   - `mark_as_read` best-effort no início do turno (MELHORIAS #11).
   - Mídia sem texto (áudio/vídeo) → `msg_midia_nao_suportada` + revisão, sem chamar IA.
   - **Identificação**: match por Telefone/ContatoSalvo-cliente → `identificacao=telefone`, nunca expira; primeira interação (sem OUT anterior) → `tpl_saudacao_cliente` renderizado com nome e retorna. Desconhecido → fluxo CPF atual, com fix do falso positivo (MELHORIAS #2): 11 dígitos crus só contam como CPF se `estado == AGUARDANDO_VERIFICACAO`; formatado (`.`/`-`) conta sempre.
   - **Gates**: `info_contrato|pagamento|segunda_via` exigem identificado; `info_contrato|pagamento` exigem DB fresca (como hoje). **Novo**: `info_contrato` com `identificacao=cpf` + `tipo_contato=DESCONHECIDO` → `msg_info_negada_desconhecido` (só boleto para desconhecidos).
   - **Ações**: pagamento pronto → `_criar_solicitacoes` + `msg_solicitacao_criada` (nunca mais texto da IA); pagamento incompleto → pergunta de slot determinística; `info_contrato` → `renderizar_infos_contrato`; `faq_id` → FAQRespostas ordenadas (como hoje); **fallback** → `criar_ou_incrementar_faq_sugerida(pergunta_sugerida_faq or texto, conv)` + revisão + `msg_fallback_sem_resposta`.
   - **`responder()`**: `enviado_ok = client.send_text(...)`; persistir sempre com a flag; `False` → marca revisão (MELHORIAS #9).
   - Log de auditoria no fim do turno: "IA classificou X / gate aplicou Y" (MELHORIAS #12).
4. **Simulador**: adaptar `SimulatorChatAPIView` ao novo schema.

## WS-B — Mídia + painel de conversas + FAQ sugeridas (depende de F0)

**Arquivos:** `www/api/serializers.py`, `www/api/views.py` (ConversaViewSet + novo ViewSet), `www/api/urls.py`, `www/whatsapp/views.py`, `frontend/.../conversations.component.ts`, `faq.component.ts`, `services/api.service.ts`, `app.component.*` (badge).

1. **Fix do wiring de mídia**: criar `MensagemPainelSerializer` (= `MensagemSerializer` de `serializers.py:177` **sem** `payload_bruto`, lendo o campo persistido `Mensagem.tipo_midia` com fallback ao parse do payload para legado, + `arquivo` URL + `enviado_ok`); trocar em `ConversaDetailSerializer.get_mensagens` (`serializers.py:322`). Isso sozinho ativa a renderização de imagem/áudio/vídeo/documento já escrita no frontend (`conversations.component.ts:173-201`) via endpoint de download existente (`views.py:799-882`).
2. **Webhook** (`whatsapp/views.py:44-53`): `_extrair_texto` → `_extrair_conteudo(message) -> (texto, tipo_midia)` cobrindo `audioMessage` e `videoMessage` (hoje ignorados); preencher `Mensagem.tipo_midia` na criação IN/OUT.
3. **Envio de arquivo pelo operador**: action `POST /api/conversas/{id}/enviar-arquivo/` (MultiPartParser, padrão de `SolicitacaoViewSet.boletos` `views.py:1290`): valida extensão/tamanho (~16MB, teto WhatsApp), cria `Mensagem` OUT (`arquivo`, `tipo_midia` por mimetype, `texto=legenda`), envia via `EvolutionClient.send_file` (`evolution_client.py:104` já cobre image/video/audio/document), grava `enviado_ok`.
4. **FAQ Sugeridas**: `FAQSugeridaViewSet` (`faqs-sugeridas` no router): list com filtro status, `POST {id}/aprovar/` (payload `{pergunta_final, respostas:[{ordem,texto}]}` → cria FAQ+FAQRespostas em transação, marca aprovada/revisado_por), `rejeitar/`, PATCH/DELETE. Dashboard stats (`views.py:193`): incluir `faqs_sugeridas_pendentes`.
5. **Frontend**:
   - `api.service.ts`: `enviarArquivoConversa`, `getFaqsSugeridas`, `aprovarFaqSugerida`, `rejeitarFaqSugerida`.
   - Conversas: botão anexar (input file oculto) + preview + legenda + spinner/erro; indicador de falha quando `enviado_ok === false`; player de áudio já existe no template.
   - FAQs: aba "Sugestões pendentes (N)" ordenada por ocorrências; "Aprovar" abre editor de FAQ pré-preenchido; badge de pendentes no menu lateral via dashboard stats.
   - Config: seção "Respostas de contrato" com os novos campos `tpl_*` e hint dos placeholders válidos por template.

## WS-C — Responsividade mobile (independente; conversas/faq só após merge do WS-B)

**Arquivos:** `frontend/src/styles.css`, `app.component.css/html`, componentes dashboard, customers, config, simulator, whatsapp, import-data, login; conversations/faq **por último**.

- Breakpoints canônicos em `styles.css` (`<640` mobile, `640–1023` tablet, `≥1024` desktop) + utilitários globais: `.table-scroll` (overflow-x:auto), `.stack-sm`, `.hide-sm`. Hoje só existem 2 media queries no projeto todo.
- **Remover larguras fixas inline** dos templates (principal causa de quebra) → `max-width`/`%`/`minmax()`.
- Tabelas: scroll container em customers/dashboard; lista de conversas vira cards no mobile.
- Ordem por uso real: conversations → dashboard → customers → faqs → config → simulator → whatsapp → import-data → login. Validar sidebar hambúrguer/overlay (já tem base em `app.component.css:177-202`).

## WS-D1 — CI + testes do código existente (independente, pode começar já)

**Arquivos:** `.github/workflows/ci.yml`, `www/core/tests.py`, `www/ia/tests.py`, parte de `www/whatsapp/tests.py`, `frontend/src/app/**/*.spec.ts` (api.service, auth.guard).

- **CI** (`ci.yml`, push/PR): job `backend` (Python 3.12, `DB_ENGINE=sqlite DJANGO_IS_PRODUCTION=0`, `pip install -r www/requirements.txt`, `makemigrations --check --dry-run`, `manage.py test -v2` todos os apps, `check --deploy --fail-level WARNING` com env de prod fake) + job `frontend` (Node 22, `npm ci`, `ng build --configuration production`, `ng test --watch=false --browsers=ChromeHeadless`). Sem CD.
- Testes de funções puras existentes: `validar_cpf`, `parse_nome_salvo`, `BotConfig.database_atualizada`, `_classificar_contato` (Telefone com/sem 9º dígito, ContatoSalvo, PHN_, desconhecido), filtro de contratos ativos/liquidados, fallback de `extrair_intencao` sem API key.

## WS-D2 — Testes dos fluxos novos + documentação (depende de WS-A e WS-B)

**Arquivos:** `www/whatsapp/tests.py`, `www/api/tests.py`, `www/README.md`, `docs/`, specs de componentes.

- **whatsapp** (mocks de `get_client()` e `extrair_intencao`): telefone cadastrado → saudação nominal sem CPF e nunca expira; desconhecido exige CPF; desconhecido verificado pedindo info → `msg_info_negada_desconhecido`; `info_contrato` → texto do template (nunca da IA); fallback cria FAQSugerida + revisão; regressão do falso positivo de CPF (telefone 11 dígitos); lock/coalescência; `enviado_ok=False` → revisão; `_extrair_conteudo` para os 6 tipos de message.
- **respostas_contrato**: cada template, placeholder inválido não explode, moeda/data, multi-contrato, prazo ausente=30, sem ativos.
- **ia**: assert de que o prompt **não contém valores financeiros** (garantia de privacidade literal).
- **api**: detail traz `possui_midia/tipo_midia`; `enviar-arquivo` (mock send_file); faqs-sugeridas list/aprovar/rejeitar/permissões.
- **frontend**: `conversations.component.spec` (renderiza mídia, anexo chama service com FormData), `faq.component.spec` (aba sugeridas).
- **Docs**: `www/README.md` + `docs/telas.md` — 1 parágrafo por rota (propósito, ações, endpoints), glossário de placeholders dos templates, fluxo do bot atualizado; atualizar `www/AGENTS.md` (invariantes novos) e regenerar `schema.yml`.

## WS-E — Hardening de produção (independente)

**Arquivos:** `www/penhorzap/settings.py`, `deploy.sh`, `www/core/management/commands/import_sqlite.py`, `.git/config` (fora do repo).

1. **Token git** (dia zero, ver topo).
2. **settings.py**: SECRET_KEY obrigatória em prod (`raise ImproperlyConfigured`); remover `http://` de `CSRF_TRUSTED_ORIGINS`; `SECURE_HSTS_SECONDS=31536000` (+subdomains/preload), `SESSION_COOKIE_HTTPONLY=True`, `SECURE_REFERRER_POLICY`; logging com `RotatingFileHandler` → `PROJECT_ROOT/logs/django.log` (10MB×5) mantendo console, loggers `whatsapp`/`ia` dedicados.
3. **deploy.sh**: backup de DB antes de `migrate` (sqlite `cp`, mysql `mysqldump | gzip`, reter 7); `check --deploy` como gate; healthcheck falha = fail (não warn) com instrução de rollback; `git tag deploy-YYYY-MM-DD-HHMM` por deploy; incluir testes de core/whatsapp/ia na etapa 1 (hoje só api).
4. **Normalização de CPF** (MELHORIAS #7): migração pós-F0 normalizando `Cliente.cpf` para 11 dígitos + ajuste no `import_sqlite` → buscas exatas, elimina hack `icontains`.

---

## Ordem de merge e regras de propriedade

```
Token git (imediato) → F0 → [WS-E ‖ WS-D1 ‖ WS-C(telas exceto conversas/faq)]
                          → WS-A → WS-B → WS-C(conversations/faq) → WS-D2 → deploy
```

- `core/models.py`/migrações: **exclusivo da F0** (migração de CPF do WS-E vem depois, numerada em sequência).
- `api/views.py`: WS-A só `SimulatorChatAPIView`; WS-B ConversaViewSet + ViewSet novo no fim — regiões disjuntas, mergear A antes de B.
- `whatsapp/tasks.py` e `mensagens_defaults.py`: exclusivos do WS-A (renderer em arquivo novo; webhook fica no WS-B).
- `conversations/faq.component.ts`: WS-B é dono; WS-C entra depois.

## Riscos

- Backfill de `Mensagem.tipo_midia` em tabela grande — rodar fora de horário; backup antes (deploy.sh já endurecido).
- Novo schema quebra o simulador — adaptação incluída no WS-A.
- Templates editáveis com placeholder inválido — renderer SafeDict é obrigatório.
- Mudanças em `tasks.py`/`services.py` exigem **restart do qcluster** (usar `./deploy.sh`, não `make deploy`).
- `graphify update .` após os merges (regra do CLAUDE.md do projeto).

## Verificação (fim a fim)

1. `make test` (agora cobrindo core/whatsapp/ia/api) + `cd frontend && npx ng test --watch=false` + `make lint`.
2. **Simulador** (`/painel` → Simulator): cliente com telefone cadastrado → saudação nominal sem pedir CPF; "qual o valor pra renovar 60 dias?" → resposta vem do template `tpl_contrato_renovacao` com valores do banco; pergunta fora de escopo → `msg_fallback_sem_resposta` + aparece em FAQ Sugeridas → aprovar → refazer a pergunta → resposta da FAQ criada.
3. **WhatsApp real** (número de teste): enviar imagem/áudio → aparecem e tocam no painel; operador envia imagem com legenda pelo painel → chega no WhatsApp; desconhecido pede dados → recebe `msg_info_negada_desconhecido`.
4. Medir tokens: logar `usage_metadata` da resposta Gemini antes/depois (esperado ~−60% input).
5. Abrir o painel em viewport 390px (devtools) — todas as telas navegáveis sem scroll horizontal.
6. Push para GitHub → CI verde nos dois jobs.
7. `./deploy.sh` — confirmar backup criado, migrações ok, healthcheck passa, qcluster reiniciado.
