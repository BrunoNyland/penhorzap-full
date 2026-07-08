# App `painel` — painel administrativo (staff-only)

Admin customizado em `/painel/` (não é o `/admin/` do Django): dashboard,
configuração do bot e das mensagens/prompt, CRUD de FAQ, lista/detalhe de
clientes e atendimentos, e um simulador da IA. A raiz `/` redireciona p/ o
dashboard.

## Arquivos

| Arquivo | O que faz | Editar quando... |
|---|---|---|
| `views.py` | `dashboard`, `mensagens_config`, `bot_config`, `faq_*` (CRUD + toggle), `cliente_list`/`cliente_detail`/`cliente_toggle_bloqueio`, `atendimento_list`/`atendimento_detail`, `simulador_chat`. Todas staff-only. | quiser mudar uma tela do painel ou o que ela mostra/faz. |
| `forms.py` | `MensagensConfigForm` (textos/prompt), `BotConfigForm` (ativo, freshness, horário de encerramento, responder desconhecidos, dias resgate), `FAQForm`, `SimuladorForm`. | quiser mudar os campos editáveis de config/FAQ. |
| `urls.py` | Rotas: `/painel/` (dashboard), `mensagens/`, `bot/`, `faqs/*`, `clientes/*`, `atendimentos/*`, `simulador/`. | quiser mudar as URLs do painel. |
| `templates/painel/base.html` | Layout base (sidebar + topbar). Todas as telas estendem este. | quiser mudar o layout/menu do painel. |
| `templates/painel/*.html` | Uma por tela: `dashboard`, `mensagens_config`, `bot_config`, `faq_list`/`faq_form`/`faq_confirm_delete`, `cliente_list`/`cliente_detail`, `atendimento_list`/`atendimento_detail`, `simulador`. | quiser mudar o HTML de uma tela. |
| `static/painel/painel.css` | CSS único do painel, da página de QR e do login do admin (`body.login`). | quiser mudar o visual. |
| `admin.py` / `tests.py` | Stubs vazios (models no admin Django estão em `core/admin.py`). | — |

## Quero um comportamento — onde edito?

- Mudar o **dashboard** (métricas/cards) → `views.py:dashboard` + `templates/painel/dashboard.html`.
- Mudar a tela de **config do bot** (ligar, freshness, encerramento) → `views.py:bot_config` + `forms.py:BotConfigForm` + `templates/painel/bot_config.html`.
- Mudar a tela de **mensagens/prompt** → `views.py:mensagens_config` + `forms.py:MensagensConfigForm` + `templates/painel/mensagens_config.html`.
- Mudar o **CRUD de FAQ** → `views.py:faq_*` + `templates/painel/faq_*.html`.
- Mudar a **lista/detalhe de cliente** ou bloqueio de IA → `views.py:cliente_*`.
- Mudar o **simulador** da IA → `views.py:simulador_chat` + `templates/painel/simulador.html`.
- Mudar o **visual** (sidebar, cores, login) → `static/painel/painel.css`.
- Mudar o **menu/sidebar** → `templates/painel/base.html`.

## Gotchas

- Login do painel = login do admin Django (`/admin/login/`), com template customizado em `../templates/admin/login_penhorzap.html`.
- As config são singletons (`MensagensConfig`/`BotConfig`); o form sempre edita a mesma linha.
- Ativar o bot pelo **QR code** (`whatsapp:toggle_bot`) dispara sync+replay; pela tela `/painel/bot/` hoje só salva `ativo` (ver `../MELHORIAS.md` #3).

Veja também: `../core/README.md` (models/config) e `../whatsapp/README.md` (QR/toggle).
