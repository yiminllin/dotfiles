# Explanation choices

The starting skill decides whether to ask. The PR writer selects the presentation for first drafts unless the user opts into the menu. When asking, read enough source to make a useful recommendation. In one `ask_user_question` call, offer up to four relevant unanswered choices. Put the recommendation first, append `(Recommended)` to its label, and explain why. Use a compact rendered preview only when it helps compare layouts. If the tool is unavailable, ask in chat and wait.

| Choice | Offer when relevant |
|---|---|
| Scope | One mechanism or path, this PR, or the full stack. Name the actual boundaries in the proposed choices. |
| Detail | Conceptual roles, exact source names and types, or mixed (plain overview with exact key handoffs and focused details). |
| Comparison | Current behavior or before/after at named revisions. |
| Diagram template | Box flow, before/after boxes, numbered overview, or tree (current or aligned comparison). |
| Explanation view | Plain explanation, ASCII diagram, core code, or LaTeX; allow useful combinations. |
| Core-code view | Source excerpt, simplified code, or pseudocode. |
| PR structure | Brief, focused, or grouped (numbered overview + details). |

For combined requests, use the starting skill's menu, not the union of all menus. Bundle related choices into concrete proposals (e.g. “aligned box comparison + core pseudocode” or a group-to-view mapping). Pass the selected scope, revisions, views, templates and detail to delegated skills. Do not show a nested menu.

An explicit request, an approved example with an instruction to reuse it, or explicit delegation can resolve choices. A recommendation, silence, or cancellation cannot. If a material choice remains unanswered, wait. If evidence invalidates a choice, explain why and ask about that choice only. Keep the other choices. A request to change only one section should not reopen choices for other sections.

Once the starting skill resolves the choices, render or write a complete first draft at that detail. Only stage a separate layout draft if the user asks. Comparison styling is automatic, not a menu item. Choices and draft acceptance do not authorize publication.
