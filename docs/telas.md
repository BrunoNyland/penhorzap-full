# Telas do painel (Angular, `/painel/`)

Uma seção por rota do SPA (`frontend/src/app/app.routes.ts`). Todas as rotas
exceto `/login` passam por `authGuard` (sessão do Django admin, staff-only).
"Endpoints consumidos" lista as chamadas de `frontend/src/app/services/api.service.ts`
(prefixo sempre `/api/`, definidas em `www/api/urls.py`).

## `/login`

**Propósito**: autenticar o operador com as mesmas credenciais do Django
admin (usuário staff).

**Ações**: formulário usuário/senha; em sucesso redireciona para
`/dashboard`.

**Endpoints**: `POST /api/auth/` (`{action: "login", username, password}`,
via `AuthView`) — devolve 403 se o usuário não é staff, 401 se a senha está
errada. `GET /api/auth/` checa sessão ativa (usado pelo `authGuard`).

## `/dashboard`

**Propósito**: visão geral operacional — volume de solicitações, qualidade
da IA (taxa de revisão humana), boletos enviados, padrões sazonais e o badge
de FAQs sugeridas pendentes de curadoria.

**Ações**: só leitura; navegação para as demais telas.

**Endpoint**: `GET /api/dashboard/` (`DashboardStatsAPIView`) — inclui,
entre outras chaves, `por_tipo`, `por_status`, `serie_30_dias`,
`total_clientes`, `solicitacoes_precisa_humano`, `conversas_precisa_revisao`,
`buckets_dia_mes` e **`faqs_sugeridas_pendentes`** (contagem de
`FAQSugerida.status=pendente`, usada para o badge no menu lateral e na aba
"Sugestões pendentes" da tela de FAQs).

## `/conversations`

**Propósito**: histórico de conversas do WhatsApp em formato chat —
mensagens de texto e mídia (imagem/áudio/vídeo/documento) recebidas do
cliente, respostas do bot/operador, e sinalização de falha de envio.

**Ações**: filtrar por estado da conversa, "precisa revisão humana" e tipo
de contato (cliente/pessoal/desconhecido); buscar por nome/CPF/número;
responder manualmente (texto) direto pelo painel; anexar e enviar um arquivo
(imagem/áudio/vídeo/documento, botão de anexo com preview + legenda,
indicador de progresso e de falha quando `enviado_ok === false`); marcar/
desmarcar revisão humana; "Limpar todas" (apaga o histórico de conversas —
ação destrutiva, usada em ambiente de testes).

**Endpoints**:
- `GET /api/conversas/?estado=&revisao=&tipo_contato=&q=` — lista
  (`ConversaListSerializer`).
- `GET /api/conversas/<id>/` — detalhe (`ConversaDetailSerializer`), inclui
  `mensagens` (via `MensagemPainelSerializer`: `possui_midia`, `tipo_midia`,
  `legenda`, `arquivo`, `enviado_ok` — **nunca** `payload_bruto`, que
  guardaria o payload bruto da Evolution) e `solicitacoes`.
- `POST /api/conversas/<id>/toggle-revisao/` — alterna
  `precisa_revisao_humana`.
- `POST /api/conversas/<id>/enviar/` (`{texto}`) — resposta manual de texto.
- `POST /api/conversas/<id>/enviar-arquivo/` (multipart, campos `arquivo` +
  `legenda` opcional) — valida extensão (imagens/áudio/vídeo/pdf/doc/xls) e
  tamanho (máx. 16MB, teto prático do WhatsApp), cria `Mensagem` OUT com
  `arquivo`/`tipo_midia`, envia via Evolution (`send_file`) e grava
  `enviado_ok`.
- `POST /api/conversas/limpar-todas/` — apaga todas as conversas.
- `GET /api/conversas/<id>/mensagens/<mensagem_id>/media/` — baixa/decodifica
  a mídia original de uma mensagem IN legada (via Evolution
  `getBase64FromMediaMessage`).

## `/customers`

**Propósito**: cadastro de clientes (espelho do ERP legado) — telefones,
contratos de penhor, histórico de conversas e solicitações; bloqueio de IA
por cliente (lista negra).

**Ações**: buscar por nome/CPF; filtrar bloqueados / só com contrato ativo;
abrir detalhe de um cliente; bloquear/desbloquear atendimento automático
(com motivo).

**Endpoints**: `GET /api/clientes/?q=&bloqueado=&ativos_somente=`
(`ClienteListSerializer`); `GET /api/clientes/<cpf>/`
(`ClienteDetailSerializer`); `POST /api/clientes/<cpf>/toggle-bloqueio/`
(`{acao: "bloquear"|"desbloquear", motivo}`).

## `/faqs`

**Propósito**: CRUD de perguntas frequentes (respostas determinísticas do
bot) **e** curadoria das perguntas que a IA não conseguiu responder
(fallback do motor novo).

**Ações**:
- Aba principal: criar/editar/ativar-desativar/excluir FAQ; cada FAQ tem uma
  ou mais `FAQResposta` (texto e/ou arquivo), enviadas em sequência
  (`ordem`) quando o bot classifica a mensagem do cliente com aquele
  `faq_id`. Só FAQs `ativo=True` entram no prompt da IA.
- Aba "Sugestões pendentes (N)": lista `FAQSugerida` (ordenada por
  `ocorrencias` desc.) geradas automaticamente pelo fallback do bot
  (`FAQSugerida.registrar`, ver `docs/fluxo-bot.md`). "Aprovar" abre um
  editor pré-preenchido com a pergunta sugerida (editável) e permite montar
  as respostas — ao confirmar, cria uma FAQ real + `FAQResposta`s e marca a
  sugestão como `aprovada`. "Rejeitar" descarta sem criar FAQ.

**Endpoints**:
- FAQ: `GET/POST /api/faqs/`, `PUT /api/faqs/<id>/`, `DELETE /api/faqs/<id>/`,
  `POST /api/faqs/<id>/toggle/`.
- FAQ sugerida: `GET /api/faqs-sugeridas/?status=pendente|aprovada|rejeitada`,
  `PATCH /api/faqs-sugeridas/<id>/` (editar pergunta antes de aprovar),
  `DELETE /api/faqs-sugeridas/<id>/`,
  `POST /api/faqs-sugeridas/<id>/aprovar/`
  (`{pergunta_final?, respostas: [{ordem, texto}]}` — cria `FAQ` +
  `FAQResposta`s numa transação, marca `status=aprovada`,
  `faq_criada`, `revisado_por=<usuário logado>`, `revisado_em`),
  `POST /api/faqs-sugeridas/<id>/rejeitar/` (marca `status=rejeitada`,
  `revisado_por`, `revisado_em`).

## `/config`

**Propósito**: liga/desliga do processamento automático (`BotConfig`) e
edição de todos os textos que o bot envia — o prompt do classificador
(`system_prompt`) e todas as `msg_*`/`tpl_*` de `MensagensConfig`, com
"restaurar padrão" por campo (defaults em
`www/core/mensagens_defaults.py`).

**Ações**: ajustar `freshness_horas` (janela de "database atualizada"),
`horario_encerramento` (desligamento automático diário),
`responder_desconhecidos`, `dias_resgate_garantia`; editar cada mensagem/
template com hint dos placeholders válidos (ver glossário abaixo);
restaurar um campo específico ao valor padrão.

**Endpoints**: `GET/PATCH /api/configs/bot/` (`BotConfigSerializer`);
`GET/PATCH /api/configs/mensagens/` (`MensagensConfigSerializer`);
`POST /api/configs/mensagens/` (`{campo}` → restaura só aquele campo ao
default e devolve a config inteira).

## `/whatsapp`

**Propósito**: pareamento com a Evolution API (QR code) e liga/desliga geral
do bot.

**Ações**: exibir estado da conexão (`open`/`connecting`/`close`); mostrar
QR code quando desconectado; ligar o bot (dispara
`sincronizar_contatos` + `processar_nao_lidas` em background via
django-q2) / desligar.

**Endpoints**: `GET /api/whatsapp/state/` (`WhatsappConnectionView`, chama
`EvolutionClient.get_connection_state`/`get_qrcode_base64`);
`POST /api/whatsapp/state/` — alterna `BotConfig.ativo` e, ao ativar,
enfileira as duas tasks acima.

## `/importar-dados`

**Propósito**: importar um snapshot do ERP legado (SQLite `0886.sqlite3`) —
clientes, contratos, telefones — mantendo o painel/bot com dados frescos.
Carimba `BotConfig.ultima_atualizacao_dados` (usado pelo freshness check que
os gates de `info_contrato`/`pagamento` exigem).

**Ações**: upload do arquivo `.sqlite3`; acompanhar status do job
(pendente/andamento/concluído/falhou) com contagens por tabela; ver
histórico de importações anteriores.

**Endpoints**: `POST /api/import/sqlite/` (multipart, cria `ImportDataJob` e
processa — idempotente, upsert em lote); `GET /api/import/sqlite/<id>/status/`;
`GET /api/import/sqlite/latest/` (histórico).

## `/simulator`

**Propósito**: testar a conversa do bot (identificação, gates, templates de
contrato, FAQ, fallback) sem tocar no WhatsApp real — cada mensagem chama o
Gemini de verdade (`extrair_intencao`), mas a resposta exibida é sempre o
resultado do renderer determinístico (`respostas_contrato.py`) ou de uma
FAQ, nunca texto gerado pela IA.

**Ações**: selecionar um cliente real (opcional — testar como desconhecido
também); enviar mensagens de teste; ver, por turno, a classificação de
depuração (`tipo_intencao`, `faq_id`, `infos_contrato`, `precisa_humano`);
reiniciar a conversa simulada; remover o cliente selecionado.

**Endpoints**: `GET/POST /api/simulador/` (`SimulatorView`, sessão de
simulação com `acao: selecionar_cliente|enviar|reiniciar|remover_cliente`);
`POST /api/simulador/chat/` (`SimulatorChatAPIView`, variante stateless usada
por alguns fluxos do componente).

---

## Glossário de placeholders (`MensagensConfig`, editáveis em `/config`)

Renderizados por `whatsapp/respostas_contrato.py:render_template`
(`str.format_map` tolerante — placeholder desconhecido vira o próprio
`{nome}` literal em vez de quebrar o envio; ver `docs/fluxo-bot.md`).

| Campo | Placeholders | Quando é usado |
|---|---|---|
| `tpl_saudacao_cliente` | `{saudacao}`, `{nome}` | Primeira interação de cliente identificado por telefone; também usado para saudação de identificado em qualquer turno. |
| `tpl_contrato_vencimento` | `{contrato}`, `{vencimento}` | `info_contrato` com `info=vencimento`. |
| `tpl_contrato_renovacao` | `{contrato}`, `{prazo_dias}`, `{valor_renovacao}`, `{vencimento}` | `info_contrato` com `info=valor_renovacao`. Sem `prazo_dias` informado pelo cliente, assume 30 e acrescenta nota "(prazo padrão de 30 dias)"; prazo arbitrário mapeia para o campo `vlr_renovacao_<N>` mais próximo entre 30/60/90/120/150/180. |
| `tpl_contrato_quitacao` | `{contrato}`, `{valor_quitacao}`, `{vencimento}` | `info_contrato` com `info=valor_quitacao` (usa `ContratoPenhor.vlr_liquido`). |
| `tpl_contrato_parcela` | `{contrato}`, `{valor_parcela}` | `info_contrato` com `info=valor_parcela`; contratos com `parcelado=False` são pulados silenciosamente. |
| `tpl_contrato_resumo` | `{contrato}`, `{vencimento}`, `{valor_emprestimo}` | `info_contrato` com `info=lista_contratos`/`detalhe_contrato`; também usado na pergunta de slot de pagamento incompleto. |
| `tpl_lista_header` | `{nome}`, `{qtd}` | Envolve o bloco quando mais de um contrato responde ao mesmo pedido (multi-contrato). |
| `tpl_lista_footer` | *(nenhum)* | Fecha o bloco multi-contrato. |
| `msg_saudacao` | `{saudacao}` | Saudação genérica (contato não identificado/desconhecido). |
| `msg_cadastro_nao_localizado` | *(nenhum)* | Desconhecido (`tipo_contato=desconhecido`) pedindo algo que exige identificação. |
| `msg_pedir_cpf` | *(nenhum)* | Contato não-desconhecido (ex.: `PHN_` sem cliente cadastrado) pedindo algo que exige identificação: pede CPF completo. |
| `msg_cpf_invalido` | *(nenhum)* | CPF digitado falha no checksum (`core.utils.validar_cpf`). |
| `msg_cpf_nao_bate` | *(nenhum)* | CPF digitado é válido mas não bate com o cadastro do contato conhecido. |
| `msg_verificacao_ok` / `msg_verificacao_falhou` | *(nenhum)* | Reservadas para o fluxo legado de verificação por 3 dígitos (ver `www/MELHORIAS.md`). |
| `msg_db_desatualizada` | *(nenhum)* | `info_contrato`/`pagamento` pedidos com `BotConfig.database_atualizada()=False`. |
| `msg_sem_contratos_ativos` | *(nenhum)* | Cliente identificado sem nenhum `ContratoPenhor` ativo. |
| `msg_solicitacao_criada` | *(nenhum)* | `pagamento` com todos os dados prontos: `Solicitacao`(ões) criada(s). |
| `msg_boleto_intro` / `msg_renovacao_proximo_vencimento` / `msg_quitacao_garantia` | `{proximo_vencimento}` / `{data_resgate}` | Sequência de mensagens ao enviar boleto (`api.tasks.enviar_boletos`), fora do fluxo de `process_mensagem`. |
| `msg_segunda_via_confirma` | `{contratos}`, `{tipo}` | `segunda_via`: pede confirmação antes de reenviar o boleto do dia anterior. |
| `msg_insistiu_humano` / `msg_neutra_padrao` | *(nenhum)* | Mensagens neutras de fallback/graceful degradation (bot desligado, erro). |
| `msg_fallback_sem_resposta` | *(nenhum)* | `duvida_geral` sem `faq_id` correspondente (ou qualquer intenção não tratada): também cria uma `FAQSugerida`. |
| `msg_info_negada_desconhecido` | *(nenhum)* | Cliente identificado só por CPF (nunca por telefone) e `tipo_contato=desconhecido` pedindo `info_contrato`: só o boleto tem os dados, nunca o chat. |
| `msg_midia_nao_suportada` | *(nenhum)* | Mensagem de áudio/vídeo/imagem/documento sem texto/legenda: bot não chama a IA, pede para escrever. |
| `system_prompt` | *(nenhum — é a instrução do Gemini, não um template renderizado)* | Ver `docs/fluxo-bot.md` para o contrato completo da IA. |

### Fluxo de aprovação de FAQ sugerida

1. Bot cai no fallback (`process_mensagem`, passo 14): nenhuma FAQ ativa
   corresponde à pergunta e nenhuma outra ação se aplica.
2. `FAQSugerida.registrar(pergunta_sugerida_faq or texto_original, conversa, pergunta_original)`
   cria uma linha `status=pendente` — ou, se já existir uma pendente com a
   mesma pergunta (case-insensitive), só incrementa `ocorrencias`.
3. Conversa é marcada `precisa_revisao_humana=True` e o cliente recebe
   `msg_fallback_sem_resposta`.
4. No painel (`/faqs`, aba "Sugestões pendentes"), o operador revisa,
   edita a pergunta se necessário e aprova com uma ou mais respostas →
   `POST /api/faqs-sugeridas/<id>/aprovar/` cria a `FAQ` real (`ativo=True`)
   + `FAQResposta`s, e marca a sugestão `aprovada`/`faq_criada`/
   `revisado_por`/`revisado_em`. A partir daí, a nova FAQ entra no prompt da
   IA (id+pergunta) e futuras perguntas equivalentes são respondidas via
   `faq_id` (passo 12 de `process_mensagem`), não mais pelo fallback.
5. "Rejeitar" apenas marca `status=rejeitada` sem criar FAQ (útil para
   perguntas fora de escopo ou spam).
