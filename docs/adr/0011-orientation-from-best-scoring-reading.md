---
status: superseded by ADR-0012
---

# Derive reading orientation from the best-scoring reading

Reading Orientation is decided by which rotation produces the most card-like OCR text, not by asking the image AI what rotation to apply. This supersedes the separate orientation check of ADR 0008: the deployed 8B vision model answers a geometric question ("how many degrees?") far less reliably than it reads text, and its answers varied card to card. Recognition rotates the perspective-corrected Business Card through the four right angles, scoring each reading by how many business-card elements it contains — postal code, telephone, fax, email, website, corporate suffix, prefecture — and stops at the first reading that reaches the acceptance threshold, falling back to the highest-scoring rotation when none does. Rotations are tried upright-first for a landscape crop and sideways-first for a portrait one, since landscape cards predominate. Only the winning reading becomes a Recognition Result; the rotations tried and their scores are retained as processing history. A user-supplied orientation is honoured as given and re-read without searching.
