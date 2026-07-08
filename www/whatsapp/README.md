# App `whatsapp` — webhook, motor de conversa e Evolution API

Aqui mora o **motor do bot**: o webhook que recebe mensagens da Evolution API, a
task `process_mensagem` que decide o que responder, os gates de privacidade em
Python, e o cliente da Evolution API (envio de texto/PDF, QR code, contatos).

## Arquivos

| Arquivo | O que faz | Editar quando... |
|---|---|---|
| `tasks.py` | **O motor.** `process_mensagem` (task principal: classifica contato → valida CPF → chama IA → aplica gates → cria `Solicitacao`/segunda via → responde). Helpers: `_classificar_contato`, `_buscar_cliente_por_cpf`, `_extrair_cpf_texto`, `_contratos_ativos_values` (gate de privacidade), `_criar_solicitacoes`, `_handle_segunda_via`, `responder`. Auxiliares: `processar_nao_lidas`, `verificar_encerramento`, `sincronizar_contatos`. | quiser mudar o fluxo da conversa, gates, triagem, criação de solicitação, encerramento, ou "responder desconhecidos". |
| `views.py` | `whatsapp_webhook` (recebe da Evolution, valida `X-Webhook-Token`, dedup, captura `push_name`, enfileira `process_mensagem`, **sempre ack 200**), `qrcode_view` (página de conexão), `toggle_bot` (liga/desliga e enfileira sync + replay). | quiser mudar o webhook, o token, ou o que acontece ao ativar o bot. |
| `evolution_client.py` | Cliente da Evolution API: `send_text`, `send_media_pdf`, `get_qrcode`, `instance_state`, `fetch_contacts` (agenda), `mark_as_read`. Caminho do endpoint de contatos overridável via `EVOLUTION_CONTACTS_PATH`. | quiser mudar como envia/recebe da Evolution, ou adaptar a versão da API. |
| `urls.py` | Rotas: `/webhook/whatsapp/`, `/painel/whatsapp-qr/`, `/painel/whatsapp-qr/toggle-bot/`. | quiser mudar as URLs. |
| `templates/whatsapp/qrcode.html` | Página de QR code + ligar/desligar o bot. Auto-atualiza a cada 20s. | quiser mudar a tela de conexão. |
| `models.py` / `admin.py` / `tests.py` | Stubs vazios (models estão em `core`). | — |

## Quero um comportamento — onde edito?

- Mudar a **resposta do bot** / fluxo da conversa → `tasks.py:process_mensagem`.
- Mudar quais dados de contrato a IA pode ver (privacidade) → `tasks.py:_contratos_ativos_values`.
- Mudar a **triagem de contato** (pessoal vs. cliente vs. desconhecido) → `tasks.py:_classificar_contato` (+ `core/utils.py:parse_nome_salvo`).
- Mudar como o CPF é extraído/validado → `tasks.py:_extrair_cpf_texto` + `core/utils.py:validar_cpf`.
- Mudar o que acontece ao **pagar** (criar solicitação) → `tasks.py:_criar_solicitacoes`.
- Mudar a **segunda via de boleto** → `tasks.py:_handle_segunda_via`.
- Mudar o **encerramento automático** diário → `tasks.py:verificar_encerramento` (+ `core/models.py:BotConfig.horario_encerramento`).
- Mudar o que acontece ao **ativar o bot** (sync/replay) → `views.py:toggle_bot`.
- Mudar o **webhook** (token, dedup, grupos) → `views.py:whatsapp_webhook`.
- Mudar como envia mensagem/PDF → `evolution_client.py`.

## Gotchas

- **Dois processos**: o `qcluster` roda as tasks; o gunicorn/runserver só servem HTTP. Mudou `tasks.py`? **Restart do qcluster** obrigatório.
- Gates de privacidade são em **Python** (não na IA): contratos só chegam à IA com `cpf_verificado` E `database_atualizada`; só ativos; só campos permitidos. Não migre isso p/ o prompt.
- `ia.services.extrair_intencao` **nunca levanta** — o `tasks.py` confia nesse contrato.
- Webhook **sempre** retorna 200 (mesmo com erro) p/ a Evolution não reenviar.

Veja também: `../AGENTS.md` (invariantes e fluxo) e `MELHORIAS.md` (pendências).
