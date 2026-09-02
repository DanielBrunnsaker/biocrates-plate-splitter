# Plate Splitter

A Dash web app that packs multi-study lab sample lists onto Biocrates QC1000
96-well plates as efficiently as possible, then exports the result for lab use
and for upload into Biocrates MetIDQ/WebIDQ.

## The idea

Each QC1000 plate has a fixed layout: column 1 and most of column 2 are
reserved for blanks/calibrators/QC samples, three more QC2 wells are
scattered at A6/C9/E12, and everything else (79 wells) is free for actual
samples. When you have several studies' worth of samples to run, you want to:

- use as few plates (and kits) as possible via [bin-packing](https://en.wikipedia.org/wiki/Bin_packing_problem), with sample order
  randomized (toggleable, seeded) within each box, or across a whole study if
  no boxes are set,
- keep each study's samples contiguous / on as few plates as possible rather
  than scattered,
- respect sample logistics — e.g. repeat/paired samples stay together, and
  samples are consumed in a given box order to avoid unnecessary freeze-thaw
  cycles,
- optionally balance stratification factors (e.g. sex, timepoint) across
  plates,
- when two studies have to share a plate, keep them visually and physically
  separated (left/right) rather than interleaved.

Plate Splitter takes a sample list (per study), runs a packing algorithm that
balances those constraints, and gives you:

- an interactive plate-by-plate visualization,
- an Excel workbook (summary + one sheet per plate + full sample list) for
  lab use,
- one Sample List CSV per plate, formatted for direct import into Biocrates
  MetIDQ/WebIDQ.

Input can be pasted, uploaded (CSV/Excel, including one sheet per study),
mapped column-by-column via a review step, or optionally parsed from free-form
text using a local LLM (via [Ollama](https://ollama.com)) — no data ever
leaves your machine.

## Running it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:8050.

(Optional) For AI-assisted parsing of pasted/uploaded text, run
[Ollama](https://ollama.com) locally with a model pulled — the app will pick
it up automatically.
