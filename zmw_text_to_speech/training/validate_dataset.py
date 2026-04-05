#!/usr/bin/env python3
# Usage: pip install flask && python validate_dataset.py
# Then open http://localhost:5000 in your browser.
"""Dataset validation web app for reviewing wav samples and their transcriptions."""

import csv
import json
import os
import shutil

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset")
METADATA_CSV = os.path.join(DATASET_DIR, "metadata.csv")
WAVS_DIR = os.path.join(DATASET_DIR, "wavs")
STATE_FILE = os.path.join(DATASET_DIR, "validation_state.json")
BAD_DIR = os.path.join(DATASET_DIR, "samples_bad")
BAD_CSV = os.path.join(BAD_DIR, "metadata.csv")


def load_metadata():
    entries = []
    with open(METADATA_CSV, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            if len(parts) == 2:
                entries.append({"file": parts[0], "text": parts[1]})
    return entries


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/entries")
def api_entries():
    entries = load_metadata()
    state = load_state()
    for e in entries:
        e["status"] = state.get(e["file"], "pending")
    return jsonify(entries)


@app.route("/api/mark", methods=["POST"])
def api_mark():
    data = request.json
    file_key = data["file"]
    status = data["status"]  # "good" or "bad"
    state = load_state()
    state[file_key] = status
    save_state(state)
    return jsonify({"ok": True})


@app.route("/api/update_text", methods=["POST"])
def api_update_text():
    """Update the transcription for a given entry in metadata.csv."""
    data = request.json
    file_key = data["file"]
    new_text = data["text"]
    entries = load_metadata()
    for e in entries:
        if e["file"] == file_key:
            e["text"] = new_text
            break
    with open(METADATA_CSV, "w") as f:
        for e in entries:
            f.write(f"{e['file']}|{e['text']}\n")
    return jsonify({"ok": True})


@app.route("/api/apply", methods=["POST"])
def api_apply():
    """Move bad samples to samples_bad/ and update both CSVs."""
    state = load_state()
    entries = load_metadata()

    os.makedirs(BAD_DIR, exist_ok=True)

    good_lines = []
    bad_lines = []
    for e in entries:
        if state.get(e["file"]) == "bad":
            bad_lines.append(e)
            # Move the wav file
            basename = os.path.basename(e["file"])
            src = os.path.join(DATASET_DIR, e["file"] + ".wav")
            if os.path.exists(src):
                shutil.move(src, os.path.join(BAD_DIR, basename + ".wav"))
        else:
            good_lines.append(e)

    # Rewrite the original metadata.csv with only good/pending entries
    with open(METADATA_CSV, "w") as f:
        for e in good_lines:
            f.write(f"{e['file']}|{e['text']}\n")

    # Write the bad metadata.csv
    with open(BAD_CSV, "w") as f:
        for e in bad_lines:
            basename = os.path.basename(e["file"])
            f.write(f"{basename}|{e['text']}\n")

    # Clean bad entries from state
    for e in bad_lines:
        state.pop(e["file"], None)
    save_state(state)

    return jsonify({"ok": True, "moved": len(bad_lines), "remaining": len(good_lines)})


@app.route("/wavs/<path:filename>")
def serve_wav(filename):
    return send_from_directory(WAVS_DIR, filename)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dataset Validator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
  h1 { text-align: center; margin-bottom: 10px; color: #fff; }
  .stats { text-align: center; margin-bottom: 15px; font-size: 14px; color: #aaa; }
  .stats span { margin: 0 10px; font-weight: bold; }
  .stats .good { color: #4caf50; }
  .stats .bad { color: #f44336; }
  .stats .pending { color: #ff9800; }
  .apply-bar { text-align: center; margin: 15px 0; }
  .apply-bar button {
    background: #e91e63; color: #fff; border: none; padding: 10px 24px;
    border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: bold;
  }
  .apply-bar button:hover { background: #c2185b; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; }
  th { background: #16213e; padding: 10px; text-align: left; position: sticky; top: 0; z-index: 1; }
  td { padding: 8px 10px; border-bottom: 1px solid #2a2a4a; vertical-align: middle; }
  tr.good { background: #1b3d1b; }
  tr.bad { background: #3d1b1b; }
  tr.pending { background: transparent; }
  .file-col { width: 120px; font-family: monospace; font-size: 13px; }
  .text-col { font-size: 14px; }
  .actions { white-space: nowrap; width: 260px; }
  .actions button {
    border: none; padding: 6px 14px; border-radius: 4px; cursor: pointer;
    font-size: 13px; margin-right: 4px; color: #fff;
  }
  .btn-play { background: #1e88e5; }
  .btn-play:hover { background: #1565c0; }
  .btn-good { background: #388e3c; }
  .btn-good:hover { background: #2e7d32; }
  .btn-bad { background: #d32f2f; }
  .btn-bad:hover { background: #b71c1c; }
  .btn-undo { background: #757575; }
  .btn-undo:hover { background: #616161; }
  .btn-save { background: #f57c00; }
  .btn-save:hover { background: #e65100; }
  .text-col .text-display { cursor: pointer; }
  .text-col .text-display:hover { outline: 1px dashed #888; outline-offset: 2px; }
  .text-col .edit-area { width: 100%; padding: 4px 6px; font-size: 14px; font-family: inherit;
    background: #0d1b2a; color: #e0e0e0; border: 1px solid #1e88e5; border-radius: 4px; resize: vertical; min-height: 40px; }
  .edit-row { display: flex; gap: 6px; align-items: start; }
  .edit-row .edit-area { flex: 1; }
  .filter-bar { text-align: center; margin-bottom: 10px; }
  .filter-bar button {
    border: 1px solid #555; background: transparent; color: #ccc;
    padding: 5px 14px; margin: 0 3px; border-radius: 4px; cursor: pointer; font-size: 13px;
  }
  .filter-bar button.active { background: #333; color: #fff; border-color: #888; }
</style>
</head>
<body>
<h1>Dataset Validator</h1>
<div class="stats">
  <span class="good">Good: <span id="cnt-good">0</span></span>
  <span class="bad">Bad: <span id="cnt-bad">0</span></span>
  <span class="pending">Pending: <span id="cnt-pending">0</span></span>
  <span>Total: <span id="cnt-total">0</span></span>
</div>
<div class="apply-bar">
  <button onclick="applyChanges()">Apply Changes &mdash; Move Bad Samples</button>
</div>
<div class="filter-bar">
  <button class="active" onclick="setFilter('all', this)">All</button>
  <button onclick="setFilter('pending', this)">Pending</button>
  <button onclick="setFilter('good', this)">Good</button>
  <button onclick="setFilter('bad', this)">Bad</button>
</div>
<table>
  <thead><tr><th class="file-col">File</th><th class="text-col">Transcription</th><th class="actions">Actions</th></tr></thead>
  <tbody id="tbody"></tbody>
</table>
<div class="apply-bar" style="margin-top:15px;">
  <button onclick="applyChanges()">Apply Changes &mdash; Move Bad Samples</button>
</div>

<script>
let entries = [];
let currentAudio = null;
let currentFilter = 'all';

async function load() {
  const res = await fetch('/api/entries');
  entries = await res.json();
  render();
}

function updateStats() {
  const good = entries.filter(e => e.status === 'good').length;
  const bad = entries.filter(e => e.status === 'bad').length;
  const pending = entries.filter(e => e.status === 'pending').length;
  document.getElementById('cnt-good').textContent = good;
  document.getElementById('cnt-bad').textContent = bad;
  document.getElementById('cnt-pending').textContent = pending;
  document.getElementById('cnt-total').textContent = entries.length;
}

function setFilter(f, btn) {
  currentFilter = f;
  document.querySelectorAll('.filter-bar button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  render();
}

function render() {
  updateStats();
  const tbody = document.getElementById('tbody');
  const filtered = currentFilter === 'all' ? entries : entries.filter(e => e.status === currentFilter);
  tbody.innerHTML = filtered.map((e, i) => {
    const idx = entries.indexOf(e);
    const basename = e.file.replace('wavs/', '');
    return `<tr class="${e.status}">
      <td class="file-col">${basename}</td>
      <td class="text-col"><span class="text-display" ondblclick="startEdit(${idx}, this)">${escHtml(e.text)}</span></td>
      <td class="actions">
        <button class="btn-play" onclick="playAudio('${basename}.wav', this)">&#9654; Play</button>
        <button class="btn-good" onclick="mark(${idx}, 'good')">&#10003; Good</button>
        <button class="btn-bad" onclick="mark(${idx}, 'bad')">&#10007; Bad</button>
        ${e.status !== 'pending' ? `<button class="btn-undo" onclick="mark(${idx}, 'pending')">Undo</button>` : ''}
      </td>
    </tr>`;
  }).join('');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function playAudio(file, btn) {
  if (currentAudio) { currentAudio.pause(); }
  currentAudio = new Audio('/wavs/' + file);
  currentAudio.play();
}

async function mark(idx, status) {
  entries[idx].status = status;
  render();
  await fetch('/api/mark', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({file: entries[idx].file, status})
  });
}

function startEdit(idx, span) {
  const td = span.parentElement;
  const text = entries[idx].text;
  td.innerHTML = `<div class="edit-row">
    <textarea class="edit-area" id="edit-${idx}">${escHtml(text)}</textarea>
    <button class="btn-save" onclick="saveEdit(${idx})">Save</button>
    <button class="btn-undo" onclick="cancelEdit(${idx})">Cancel</button>
  </div>`;
  const ta = document.getElementById('edit-' + idx);
  ta.focus();
  ta.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); saveEdit(idx); }
    if (ev.key === 'Escape') { cancelEdit(idx); }
  });
}

function cancelEdit(idx) {
  render();
}

async function saveEdit(idx) {
  const ta = document.getElementById('edit-' + idx);
  const newText = ta.value.trim();
  if (newText === entries[idx].text) { render(); return; }
  entries[idx].text = newText;
  render();
  await fetch('/api/update_text', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({file: entries[idx].file, text: newText})
  });
}

async function applyChanges() {
  const badCount = entries.filter(e => e.status === 'bad').length;
  if (badCount === 0) { alert('No samples marked as bad.'); return; }
  if (!confirm(`Move ${badCount} bad sample(s) to samples_bad/ and update CSVs?`)) return;
  const res = await fetch('/api/apply', {method: 'POST'});
  const data = await res.json();
  alert(`Moved ${data.moved} bad samples. ${data.remaining} entries remaining.`);
  load();
}

load();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("Starting dataset validator at http://localhost:5000")
    app.run(debug=True, port=5000)
