# Do not turn a detection failure into a whole-photo card

When Card Detection finds no Extractable Business Card, it produces no Business Card instead of treating the whole Photo as one low-confidence card. This supersedes the whole-photo fallback in ADR 0010: fabricating a card hides detection failures, violates the four-corner Extraction Ground Truth and can send an unrelated or multi-card image into recognition; the user can retake the Photo or add a card by supplying its four corners.
