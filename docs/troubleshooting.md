# Troubleshooting

| Symptom | Check |
|---|---|
| Python rejected | Use Python 3.12 and `uv sync --locked --all-groups` |
| Offline dependency error | Initial sync needs package access; offline checks do not install missing dependencies |
| Output directory exists | Use a new path under `runs/`; existing evidence is not overwritten |
| Ollama unavailable or cloud enabled | Follow [daemon setup](milestones/M02.md#local-setup); settings must reach the running daemon |
| Wrong checkpoint | Run `aflab doctor`; the full Instruct tag matters, not just “Qwen 3” |
| Output limit / invalid report | Inspect raw output and stop reason; do not strip prose or change limits without recording a changed experiment |
| Valid JSON but contradicted claim | Check exact ID, title and database outcome; valid syntax is not truth |
| `report --check` returns 1 | Markdown is missing/stale; inspect before deliberate regeneration, especially historical reports |
| `report` returns 2 | Check schemas, regular JSON files, unique keys and matching observations |
| Command returns 0 but task failed | A failure was successfully recorded; read the task and claim grades |

Include the command, Python/uv version, OS and a synthetic reproduction when asking
for help. The offline quickstart needs no Ollama. See [support](../SUPPORT.md).
