# App `ia` — Gemini (classificação de intenção + resposta sugerida)

Camada de IA: chama o Google Gemini (`gemini-3.1-flash-lite`, `temperature=0.2`) com o
histórico da conversa + contratos filtrados + FAQ, recebe um JSON estruturado
(Pydantic) e devolve uma intenção + resposta sugerida. **Não toma decisão**: o
`whatsapp/tasks.py` é quem aplica os gates e executa.

## Arquivos

| Arquivo | O que faz | Editar quando... |
|---|---|---|
| `services.py` | `extrair_intencao(...)` — monta o prompt (system + histórico + contratos + FAQ + bloco ESTADO), chama o Gemini, parseia com Pydantic. **Nunca levanta** (sem `GEMINI_API_KEY`/erro → fallback neutro com `precisa_humano=True`). Import de `core.models` dentro da função p/ proteger o app registry. | quiser mudar o prompt, o modelo, a temperatura, ou o fallback. |
| `schemas.py` | Schemas Pydantic: `TipoIntencao`, `TipoPagamento`, `SolicitacaoDraft`, `IntencaoCliente`. Contrato do que a IA devolve. | quiser mudar o que a IA pode retornar (ex.: adicionar um campo/intenção). |
| `models.py` / `views.py` / `admin.py` / `tests.py` | Stubs vazios. | — |

## Quero um comportamento — onde edito?

- Mudar o **prompt** / personalidade / regras da IA → `services.py:extrair_intencao` (system prompt) — ou o default em `core/mensagens_defaults.py` / painel.
- Mudar o **modelo do Gemini** ou `temperature` → `services.py:extrair_intencao`.
- Mudar o **fallback** quando não tem API key → `services.py:extrair_intencao`.
- Mudar os **tipos de intenção** ou o que a IA devolve → `schemas.py` (e reflita no prompt).
- Mudar **gates pós-IA** (exigir CPF, exigir DB fresca) → **não aqui**; é em `whatsapp/tasks.py:process_mensagem`.

## Gotchas

- `extrair_intencao` **nunca levanta** — o `tasks.py` depende disso. Se adicionar `raise`, quebra o motor.
- A IA **nunca calcula valores**; só cita literais dos contratos que o `tasks.py` passou (já filtrados).
- Sem `GEMINI_API_KEY` o bot degrada com segurança (responde neutro, marca p/ humano).
- Mudou `services.py`? Restart do qcluster.

Veja também: `../AGENTS.md` (invariantes) e `../core/README.md` (`mensagens_defaults.py`).
