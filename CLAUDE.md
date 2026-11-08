# CLAUDE.md

## Tickets

Os tickets ficam em `.scratch/<tema>/issues/NN-<slug>.md`. Cada um tem uma linha `**Status:**` e uma lista de critérios de aceitação em checkboxes (`- [ ]`).

### Fechar um ticket

Quando o usuário disser que um ticket está fechado (fechado, concluído, done, pronto), atualize o arquivo do ticket:

1. **Identifique o ticket.** Se a mensagem não apontar um único arquivo, pergunte qual é.
2. **Encontre os commits.** Use `git log` para achar os commits que implementam o ticket. Se não estiver claro quais são, pergunte.
3. **Confira cada critério.** Para cada checkbox, confirme no código, nos testes ou rodando a suíte que o critério foi atendido. Marque `- [x]` só nos critérios confirmados.
4. **Atualize o status.** Troque a linha de status pelo formato usado nos tickets concluídos, com SHAs curtos (7 caracteres):
   - um commit: `**Status:** done (commit \`6181bb5\`)`
   - vários: `**Status:** done (commits \`c48243e\`, \`617cccd\`)`

   Se algum critério não puder ser confirmado, deixe-o `- [ ]`, mantenha o status anterior e diga ao usuário qual critério ficou pendente e por quê. Ele decide se o ticket fecha mesmo assim.

Altere só a linha de status e os checkboxes. O resto do ticket fica como está.
