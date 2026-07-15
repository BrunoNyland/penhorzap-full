# Fluxo do bot v2 (passo a passo) e contrato da IA

Referência de código: `www/whatsapp/tasks.py` (`process_mensagem` e
auxiliares), `www/whatsapp/respostas_contrato.py` (renderer determinístico),
`www/ia/services.py` (`extrair_intencao`), `www/ia/schemas.py`
(`ClassificacaoMensagem`). Testes correspondentes: `www/whatsapp/tests.py`,
`www/ia/tests.py`.

## Visão geral

```
Evolution API → webhook (whatsapp/views.py) → Mensagem IN persistida
                                                       │
                                          async_task("whatsapp.tasks.process_mensagem", id)
                                                       │
                                          process_mensagem (mutex de conversa)
                                                       │
                              classifica contato → identifica (telefone/CPF) → gates
                                                       │
                              extrair_intencao (Gemini, CLASSIFICADOR PURO)
                                                       │
                    gates pós-IA (Python) → ação determinística → responde
```

A decisão central do v2: **a IA nunca escreve o texto que o cliente recebe**.
Ela só preenche um schema JSON de classificação (`ClassificacaoMensagem`);
todo texto nasce de templates (`MensagensConfig`, editáveis em `/config`)
renderizados em Python por `respostas_contrato.py`.

## 1. Webhook e lock/coalescência

`whatsapp_webhook` (`whatsapp/views.py`) sempre responde HTTP 200 (mesmo em
erro interno — nunca fazer a Evolution reenviar o payload). Rejeita payload
sem `X-Webhook-Token` válido (403). Ignora grupos (`@g.us`). Deduplica por
`wa_message_id`. `_extrair_conteudo(message)` mapeia os 6 tipos de nó de
mensagem da Evolution para `(texto, tipo_midia)`:

| Nó do payload | texto | tipo_midia |
|---|---|---|
| `conversation` | `conversation` | `""` |
| `extendedTextMessage` | `.text` | `""` |
| `imageMessage` | `.caption` | `"image"` |
| `videoMessage` | `.caption` | `"video"` |
| `documentMessage` | `.caption` ou `.fileName` | `"document"` |
| `audioMessage` | `""` (sem legenda) | `"audio"` |

Cada `Mensagem` IN dispara `async_task("whatsapp.tasks.process_mensagem", id)`.

Dentro de `process_mensagem`, antes de qualquer processamento, um mutex leve
por conversa (`Conversa.processando_desde`) evita que duas tasks concorrentes
(replay de não-lidas + webhook, por exemplo) processem a mesma conversa ao
mesmo tempo:

- Adquire o lock numa transação curta (`select_for_update`) — **não** segura
  o lock durante a chamada ao Gemini/Evolution (só na aquisição).
- Se já havia um lock recente (< 60s), a mensagem é **reagendada** via
  `django_q.tasks.schedule` (execução única, +5s) em vez de processada —
  não responde neste turno.
- **Coalescência**: dentro do processamento, se já existe uma `Mensagem` IN
  mais nova na mesma conversa, esta task aborta silenciosamente (a task da
  mensagem mais nova cobre o turno inteiro, evitando respostas fora de
  ordem).
- `finally` sempre limpa o mutex (`processando_desde=None`), mesmo em erro.

## 2. Classificação de contato e identificação

`_classificar_contato` prioriza: `Telefone` cadastrado (match flexível com/
sem o 9º dígito) > `ContatoSalvo` sincronizado da agenda (`PHN_<cpf>_<nome>`
= cliente, senão pessoal) > `pushName` do webhook (também tenta
`PHN_`). Contato pessoal → bot ignora (dono responde manualmente). Contato
desconhecido sem nenhuma resposta anterior → saudação genérica
(`msg_saudacao`, se `BotConfig.responder_desconhecidos`).

**Identificação por telefone** (decisão do dono): se o número do WhatsApp
bate com um `Telefone` cadastrado, o contato é `tipo_contato=cliente` e
`identificacao=telefone` **imediatamente e permanentemente** — nunca expira,
nunca pede CPF. Na primeira interação (nenhum OUT anterior nesta conversa),
o bot responde com `tpl_saudacao_cliente` (nome do cliente) e encerra o
turno sem chamar a IA.

**Identificação por CPF** (contato sem telefone cadastrado): se a mensagem
contém um CPF, `core.utils.validar_cpf` valida o checksum em Python (a IA
nunca decide isso). CPF formatado (com `.` ou `-`) é reconhecido em
qualquer estado da conversa; uma sequência **crua** de 11 dígitos só conta
como CPF quando `conv.estado == aguardando_verificacao` — evita o falso
positivo de qualquer número de 11 dígitos (telefone, número de contrato)
virar CPF fora do fluxo de verificação. CPF válido e compatível com o
cadastro (se o contato já tinha um cliente vinculado) → `identificacao=cpf`,
`verified_at=agora`. **Expira em 24h** (`VERIFICACAO_VALIDADE`) — e só a
identificação por CPF expira; telefone cadastrado nunca passa por esse
check.

## 3. Mídia sem texto

Áudio/vídeo/imagem/documento sem texto/legenda associado não chama a IA:
responde direto `msg_midia_nao_suportada` e marca `precisa_revisao_humana`.

## 4. Chamada à IA — classificador puro

`extrair_intencao(mensagem_atual, historico, contratos_ativos, faqs,
identificado, db_atualizada, contato_tipo)` (`ia/services.py`) **nunca
levanta exceção**: sem `GEMINI_API_KEY`, sem o SDK instalado, ou em qualquer
erro do Gemini, degrada para um resultado neutro
(`tipo_intencao=outro, precisa_humano=True`) e o pipeline segue
normalmente — o bot nunca trava por falta de IA.

### O que entra no prompt (garantia dura de privacidade)

- **Contratos**: só chegam se `identificado AND database_atualizada`
  (`_contratos_ativos_values`, que já filtra contratos liquidados). Mesmo
  assim, `ia.services._formatar_contratos` **remove todo valor
  financeiro** — a IA só recebe `contrato=N vencimento=D parcelado=s/n`,
  o suficiente para desambiguar qual contrato o cliente quer, nunca para
  redigir um valor. Nenhum `vlr_*` (empréstimo, líquido, renovação,
  parcela) chega ao Gemini. Testado em `ia/tests.py::PrivacidadeDoPromptTests`
  (monta um contrato fake com valores distintos e verifica que nenhum
  aparece no texto do prompt).
- **FAQs**: `id` + `pergunta` apenas — nunca o texto das respostas
  (`ia.services._formatar_faqs`).
- **Dados pessoais** (CPF, endereço, telefone, aniversário) nunca entram no
  prompt.
- System prompt curto e fixo (`core.mensagens_defaults.DEFAULT_SYSTEM_PROMPT`,
  editável em `/config`) — só instruções de classificação, sem persona nem
  regras de redação, o que também habilita o cache implícito do Gemini.

### Schema de saída — `ClassificacaoMensagem` (`ia/schemas.py`)

| Campo | Tipo | Uso |
|---|---|---|
| `tipo_intencao` | `TipoIntencaoV2` (`saudacao\|duvida_geral\|info_contrato\|pagamento\|segunda_via\|outro`) | Roteamento principal. |
| `faq_id` | `int \| None` | Preenchido quando a mensagem corresponde a uma FAQ ativa. |
| `infos_contrato` | `List[InfoContratoPedido]` | Só para `info_contrato`: um item por dado pedido (`vencimento\|valor_renovacao\|valor_quitacao\|valor_parcela\|lista_contratos\|detalhe_contrato`), com `contratos` (vazio = todos) e `prazo_dias` opcional (só `valor_renovacao`). |
| `solicitacoes` | `List[SolicitacaoDraft]` | Só para `pagamento`: uma entrada por ação distinta (`tipo`, `contratos`, `prazo_dias`). |
| `pronto_para_criar_solicitacao` | `bool` | Só `True` quando todos os dados necessários já foram coletados na conversa. |
| `precisa_humano` | `bool` | Insistência/irritação do cliente, ou qualquer sinal de que um humano deve intervir. |
| `pergunta_sugerida_faq` | `str \| None` | `duvida_geral` sem `faq_id`: pergunta reescrita curta, vira `FAQSugerida`. |

Removidos do schema v1 (`IntencaoCliente`, mantido só para o histórico do
simulador legado): `resposta_sugerida`, `cpf_extraido`, `duvida_cliente`,
`resposta_faq` — nada disso existe mais porque a IA não redige texto nem
decide validade de CPF.

## 5. Gates pós-IA (regras duras em Python)

A IA nunca decide acesso — só classifica. Depois da chamada, `process_mensagem`
aplica, nesta ordem:

1. **Exige identificação** (`info_contrato`, `pagamento`, `segunda_via`) e
   `identificado=False` → se `tipo_contato=desconhecido`,
   `msg_cadastro_nao_localizado`; senão (contato "tipo cliente" mas sem
   `Cliente` resolvido, ex.: `PHN_` com CPF não cadastrado),
   `msg_pedir_cpf` e `estado=aguardando_verificacao`.
2. **Exige database fresca** (`info_contrato`, `pagamento`) e
   `BotConfig.database_atualizada()=False` → `msg_db_desatualizada` +
   revisão humana.
3. **Desconhecido verificado só por CPF pedindo `info_contrato`** —
   `identificacao=cpf AND tipo_contato=desconhecido` → `msg_info_negada_desconhecido`
   (decisão do dono: quem não está salvo no WhatsApp do dono só recebe
   dados via boleto, nunca pelo chat, mesmo com CPF verificado).
   **Pagamento continua permitido** neste caso — só a leitura direta de
   `info_contrato` é negada.

## 6. Ações determinísticas

- **`pagamento`** pronto (`pronto_para_criar_solicitacao` + `solicitacoes`)
  → `_criar_solicitacoes` (uma `Solicitacao` por draft; contratos vazio =
  todos os ativos do cliente) + `msg_solicitacao_criada`. Incompleto →
  pergunta de slot determinística (`_montar_pergunta_pagamento_incompleto`,
  lista os contratos ativos via `tpl_contrato_resumo` e pede
  contrato/prazo).
- **`segunda_via`** → `_handle_segunda_via`: localiza a última `Solicitacao`
  com boleto enviado; se foi hoje, avisa que já mandou e marca revisão; se
  foi antes de hoje, clona a solicitação e pede confirmação
  (`msg_segunda_via_confirma`), `estado=aguardando_boleto`.
- **`info_contrato`** → `respostas_contrato.renderizar_infos_contrato`
  (ver seção 7).
- **`faq_id`** presente e a FAQ existe/está ativa → envia cada
  `FAQResposta` em ordem (`ordem`); resposta com `arquivo` usa
  `EvolutionClient.send_file`, resposta só-texto usa `send_text`.
- **`saudacao`** → `tpl_saudacao_cliente` (identificado) ou `msg_saudacao`
  (não identificado).
- **Fallback** (`duvida_geral` sem `faq_id`, `outro`, ou qualquer caminho
  não coberto acima) → `FAQSugerida.registrar(pergunta_sugerida_faq or
  texto, conversa, pergunta_original)` (dedup: pergunta pendente igual,
  case-insensitive, só incrementa `ocorrencias`) + `precisa_revisao_humana`
  + `msg_fallback_sem_resposta`. Ver o fluxo de aprovação em
  `docs/telas.md`.

## 7. Renderer de contrato (`respostas_contrato.py`)

Único lugar onde valores financeiros viram texto para o cliente — sempre
lidos do banco na hora (`_contratos_ativos_values`), nunca do resultado da
IA:

- `formatar_moeda`/`formatar_data`: formatação pt-BR sem depender de locale
  do SO.
- `render_template`: `str.format_map` com um dict tolerante
  (`_SafeDict`) — um placeholder desconhecido no template editado no painel
  vira o próprio `{placeholder}` literal (loga warning) em vez de lançar
  `KeyError` e derrubar o envio.
- `renderizar_infos_contrato(cliente, pedidos, msgs)`: resolve
  `pedido.contratos ∩ ativos` do cliente; sem cliente ou sem contratos
  ativos → `msg_sem_contratos_ativos`; contratos citados que não estão
  entre os ativos são ignorados silenciosamente (a IA já é instruída a só
  usar números da lista fornecida). Prazo de renovação: se o cliente não
  informou, assume 30 dias e anexa nota "(prazo padrão de 30 dias)"; se
  informou um valor arbitrário, mapeia para o campo `vlr_renovacao_<N>`
  disponível mais próximo entre 30/60/90/120/150/180 (empate resolve para o
  menor). Parcela pula contratos com `parcelado=False`. Quando o mesmo
  pedido resolve mais de um contrato, o bloco ganha
  `tpl_lista_header`/`tpl_lista_footer` (multi-contrato); um único contrato
  não usa header/footer.

## 8. `responder()` e auditoria

`responder(texto)` sempre persiste uma `Mensagem` OUT com
`enviado_ok = client.send_text(...)` — mesmo quando o envio falha (nunca
descarta silenciosamente). `enviado_ok=False` marca
`precisa_revisao_humana=True` (a UI mostra um indicador de falha na
conversa). `responder_arquivo()` é o equivalente para `FAQResposta` com
arquivo, via `send_file`. Todo turno termina com um log de auditoria
(`_log_auditoria`): `"process_mensagem conversa=X intencao_ia=Y
precisa_humano=Z -> <ação aplicada>"`.

## Invariantes (não quebrar)

- `extrair_intencao` nunca levanta.
- Nenhum valor financeiro de contrato chega ao prompt da IA.
- A IA nunca decide validade de CPF nem acesso — isso é sempre gate em
  Python.
- Telefone cadastrado = identificado, para sempre, sem CPF.
- Só a identificação por CPF expira (24h); telefone nunca.
- Todo texto que o cliente recebe nasce de um template renderizado em
  Python, nunca de texto gerado pela IA.
- `Mensagem` OUT sempre grava `enviado_ok`, mesmo em falha de envio.
