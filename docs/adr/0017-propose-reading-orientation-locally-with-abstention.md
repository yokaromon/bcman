---
status: accepted
---

# Read Orientation locally with abstention

Each new Card Extraction will receive at most one automatic Reading Orientation proposal from a bundled local four-direction classifier, checked for rotation consistency and supported by local text-line, OCR-confidence and asymmetric-glyph evidence; conflicting or weak evidence yields Orientation Uncertain while OCR and registration continue on the photographed orientation. The managed multimodal service remains an OCR candidate but is not asked to decide rotation because its earlier geometric answers were unstable and lacked confidence suitable for Orientation Acceptance. If the local pipeline meets Orientation Acceptance on unseen cards, this decision supersedes ADR 0012; until then production retains manual orientation.
