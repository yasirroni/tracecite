# Report Structure and Analytical Voice

## Default report shape

Use only the sections the investigation needs:

```markdown
# Report title

## Executive summary

## Scope and method

## Findings

### Finding or comparison theme

## Conflicts, limitations, and unresolved questions

## References

[reference definitions]
```

A short blog post may omit formal method and limitation headings, but it must still distinguish evidence, synthesis, and uncertainty.

## Claim classes

| Class | Treatment |
|---|---|
| Direct fact | Cite immediately to the relevant source page. |
| Exact quotation | Reproduce exactly, verify with `tracecite verify quote`, and cite immediately. |
| Synthesis | Cite every material source used to combine the conclusion. |
| Inference | Label it as an inference and cite the evidence from which it follows. |
| Conflict | Present both positions, their dates and scopes, and the unresolved difference. |
| Limitation | State what the available sources cannot establish. |
| Unsupported | Remove, narrow, or mark as requiring further evidence. |

## Narrative rules

- Write for a human reader, not as an audit log or agent report.
- Put evidence where the reader needs it; do not move all proof into a detached appendix.
- Use block quotations sparingly. Prefer paraphrase when the exact wording has no analytical value.
- Keep printed report-page labels distinct from physical PDF pages. The visible text may show the printed label, while the link fragment always uses the physical PDF page.
- Avoid phrases such as “the database says”. Name the source document instead.
- Use British spelling and punctuation unless the host repository has another style.

## Conflict pattern

```markdown
The two planning reports use different retirement assumptions. The earlier report places the change in the late 2030s [2024 ISP, report p. 18][aemo-2024-isp-p22], while the later report extends the trajectory [2026 ISP, report p. 55][aemo-2026-isp-p65]. The difference is documented, but the available passages do not by themselves establish which modelling change caused it.
```

## Insufficient-evidence pattern

```markdown
The available reports establish the revised timing but do not isolate the contribution of each modelling assumption. A causal attribution would require the underlying assumptions workbook or model documentation.
```
