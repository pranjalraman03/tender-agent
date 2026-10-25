# Golden set

One JSON file per (tender, company profile) pair, validated by `evals/schema.py`.
PDFs live in `pdfs/`. Gold citations are **text snippets** from the clause that states each
requirement (clause ids change on every re-parse; snippets don't).

- `syn_*.json` are **synthetic** smoke cases built by `make_synthetic.py`. They check that the
  pipeline and metrics work; they are not quality measurements and are excluded from headline
  metrics as soon as real cases exist.
- Real cases: download the tender documents from the portal by hand, put them under
  `pdfs/<tender-id>/`, and run `uv run python evals/label_tool.py` to create the JSON.
  Target: ~50 real cases across the 2–3 focus industries, with a mix of eligible,
  not eligible and exemption outcomes.
