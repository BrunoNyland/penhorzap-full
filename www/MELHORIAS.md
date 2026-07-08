# MELHORIAS.md

Melhorias pendentes identificadas após o redesign do motor de conversa.
Ordenado por prioridade. Referências apontam para arquivos/funções reais.

## Bugs reais (corrigir primeiro)

1. **Concorrência em `process_mensagem`** (`whatsapp/tasks.py:process_mensagem`)
   — duas mensagens rápidas da mesma conversa disparam 2 tasks que leem o
   mesmo estado de `Conversa` e podem responder/criar `Solicitacao` duplicada.
   Falta `select_for_update` ou lock por conversa.

2. **Falso positivo de CPF** (`whatsapp/tasks.py:_extrair_cpf_texto`)
   — uma mensagem só de 11 dígitos (ex.: um telefone "67999755980") é tratada
   como tentativa de CPF. Deve só disparar quando formatado (`. -`), **ou**
   a conversa está em `AGUARDANDO_VERIFICACAO`, **ou** a IA marcou
   `cpf_extraido`.

3. **Painel ativa o bot sem replay/sync** — `toggle_bot` (QR) enfileira
   `sincronizar_contatos` + `processar_nao_lidas`, mas o `BotConfigForm` em
   `/painel/bot/` só salva `ativo` e não dispara nada. Mover o enqueue para
   um único helper e chamar nos dois lugares.

## Robustez do fluxo

4. **`segunda_via` não lê a conversa do dia anterior**
   (`whatsapp/tasks.py:_handle_segunda_via`) — o spec pedia reler a conversa e
   regerar a solicitação conforme ela; hoje só se clona a última `Solicitacao`
   com boleto. Também cria a solicitação **antes** do cliente confirmar, e não
   há turno de confirmação. Só criar após o "sim", guardando o clone proposto
   em `Conversa.slots`.

5. **Slot-filling frágil** — `Conversa.slots` (JSONField) existe mas **não é
   usado**. O multi-turno depende só da IA reler o histórico. Um estado
   determinístico (`{"esperando":"contratos","tipo":"renovar","cpfs":[...]}`)
   tornaria "qual contrato?", "qual prazo?" mais confiáveis e auditáveis.

6. **`Conversa` nunca fecha** — `get_or_create(remote_jid)` cria uma linha que
   vive pra sempre; `cpf_verificado` persiste entre sessões. Sem transição
   para `ENCERRADA`. Resetar ao desligar o bot ou ao fim do atendimento.

## Qualidade / correção de dados

7. **CPF não normalizado no import** (`core/management/commands/import_sqlite.py`)
   — `Cliente.cpf` vem com formatação incerta do legado, então
   `_buscar_cliente_por_cpf` faz um hack O(n) com `cpf__icontains`. Normalizar
   para 11 dígitos no import torna todas as buscas exatas e elimina o hack.

8. **`valor de quitação` → `vlr_liquido` não confirmado**
   (`whatsapp/tasks.py:_contratos_ativos_values`) — se não for o campo certo,
   o bot cita valor errado de quitação (questão financeira). Confirmar com o
   ERP, ou remover da lista permitida e deixar o valor vir só do boleto (API).

9. **`OUT` salva mesmo se `send_text` falha** (`whatsapp/tasks.py:responder`)
   — o histórico mostra resposta que o cliente não recebeu; a IA/operador
   acham que foi. Falta status de entrega (ou só persistir `OUT` no sucesso +
   fila de retentativa).

## Operação

10. **Sem testes** — `validar_cpf`, `parse_nome_salvo`, filtro de contratos
    ativos/liquidados, `BotConfig.database_atualizada()` e
    `_extrair_cpf_texto` são funções puras altamente testáveis e não têm
    suite. Maior amortizador de regressão.

11. **`mark_as_read` nunca é chamado** e o endpoint de contatos
    (`evolution_client.fetch_contacts`) é um palpite não verificado — o "não
    lidas" no WhatsApp nunca é limpo e a triagem PHN vs. pessoal pode estar
    silenciosamente inativa. Validar contra a instância Evolution v2.3.7.

12. **Sem auditoria IA × gate** — para um bot financeiro, faltaria logar "IA
    disse X / gate Python sobrescreveu para Y" para depuração e compliance.
