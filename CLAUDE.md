# CLAUDE.md

## Tickets

Os tickets abertos ficam em `.scratch/<tema>/issues/NN-<slug>.md`. Os concluídos ficam em `.scratch/closed/NN-<slug>.md`. Cada um tem uma linha `**Status:**` e uma lista de critérios de aceitação em checkboxes (`- [ ]`).

### Numeração

O número `NN` identifica o ticket em todo o `.scratch`, não só dentro do tema. Dois tickets nunca têm o mesmo número, mesmo em temas diferentes.

- **Ticket novo:** use o maior número existente em `.scratch` (abertos e `closed/`) mais um, com dois dígitos. O número aparece no nome do arquivo e no título (`# NN: ...`).
- **Referências:** cite outros tickets só pelo número (`ticket 03`, `**Blocked by:** 03 (...)`), sem o nome do tema.
- **Não renumere.** O número de um ticket não muda depois de criado, nem quando ele é fechado e movido.

### Fechar um ticket

Quando o usuário disser que um ticket está fechado (fechado, concluído, done, pronto), atualize o arquivo do ticket:

1. **Identifique o ticket.** Se a mensagem não apontar um único arquivo, pergunte qual é.
2. **Encontre os commits.** Use `git log` para achar os commits que implementam o ticket. Se não estiver claro quais são, pergunte.
3. **Confira cada critério.** Para cada checkbox, confirme no código, nos testes ou rodando a suíte que o critério foi atendido. Marque `- [x]` só nos critérios confirmados.
4. **Atualize o status.** Troque a linha de status pelo formato usado nos tickets concluídos, com SHAs curtos (7 caracteres):
   - um commit: `**Status:** done (commit \`6181bb5\`)`
   - vários: `**Status:** done (commits \`c48243e\`, \`617cccd\`)`

   Se algum critério não puder ser confirmado, deixe-o `- [ ]`, mantenha o status anterior e diga ao usuário qual critério ficou pendente e por quê. Ele decide se o ticket fecha mesmo assim. Enquanto ele não decidir, o ticket fica onde está.
5. **Mova o ticket para `.scratch/closed/`.** Mantenha o nome do arquivo, com o mesmo número. Se a pasta `issues/` do tema ficar vazia, apague-a junto com a pasta do tema.

No conteúdo do arquivo, altere só a linha de status e os checkboxes. O resto do ticket fica como está.
