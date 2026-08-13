# Multi-card detection produces duplicate cards (4 → 8)

## Symptom

A photo of 4 separate business cards, placed in mixed reading orientations
(not all rotated to face the same way), was detected as 8 Business Cards
instead of 4. The duplicate cards' cropped images are expected to be visibly
wrong/garbled (cropped from the wrong region of the source photo).

Orientation was suspected as the cause but is not related — the per-card
orientation normalization (`orient_card` / `apply_orientation`, ADR 0008)
runs independently, after detection, on each already-detected card.

## Root cause

`improve_detection()` in `Project/backend/app/services.py` (around lines
147–170) is the AI fallback pass that runs whenever local contour detection
(`detect_cards`) finds fewer than 8 cards:

```python
async def improve_detection(photo: Photo, db: Session):
    local_cards = db.query(BusinessCard).filter_by(photo_id=photo.id).all()
    if len(local_cards) >= 8 and all(card.detection_confidence >= .5 for card in local_cards): return
    encoded = encode_for_ocr(Path(photo.storage_path))
    ...
```

Since local `BusinessCard` rows always get a hardcoded `detection_confidence`
of `.75` (see `_write_card`), the confidence check is always true — the only
thing that gates the AI fallback is the card count. This means **the AI
fallback runs on essentially every real-world photo** (anything with fewer
than 8 cards), by design (ADR 0005: "eight cards is the quality target").
That part is intentional.

The bug is in how the AI's response is interpreted:

1. `encode_for_ocr()` (line ~79–88) downscales the image to at most
   `OCR_MAX_EDGE = 1600` px on the long edge before sending it to the vision
   model. This helper was written for OCR of an already-cropped single card,
   where only text legibility matters.
2. `improve_detection()` reuses this same helper to send the **whole photo**
   to the detection model, for a different purpose: finding card corners in
   pixel coordinates.
3. `DETECTION_PROMPT` (line 18) tells the model: *"Coordinates are pixels in
   the original image..."* — but the model only ever sees the downscaled
   image and has no way to know the original's true dimensions, so it
   necessarily answers in the downscaled image's pixel space.
4. The returned corners are used as-is (`cv2.boundingRect(...)`) against the
   full-resolution original image, both for deduplication and for the
   perspective-warp crop in `_write_card`.
5. Deduplication (`_iou`, threshold `> .5`) compares the AI candidate's
   wrongly-scaled box against the local candidate's true-scale box. Because
   the two are at different scales, IoU comes out near zero, so the "is this
   the same physical card?" check never matches.
6. Every already-found local card gets a second, AI-sourced entry added on
   top of it instead of replacing/merging — hence 4 real cards become 8 rows.

## Suggested fix

Don't conflate the OCR-resize helper with detection. Options, roughly in
order of robustness:

- **Best**: change `DETECTION_PROMPT` to ask for corners as fractions
  (`0.0–1.0`) of image width/height instead of absolute pixels. In
  `improve_detection`, multiply by the *original* image's width/height
  (already available — `image = cv2.imread(...)` on the full-res photo runs
  right after the AI call) to get true pixel coordinates. This is
  scale-independent and stays correct even if `OCR_MAX_EDGE` changes later.
- **Simpler but more fragile**: keep pixel coordinates, but track the resize
  ratio applied in `encode_for_ocr` (or add a detection-specific encode
  function that returns it) and multiply the AI's returned coordinates back
  up by that ratio before using them.

Either fix should be verified by re-running detection on a photo with a
known card count well under 8 and confirming the result count matches (no
duplicates), and that duplicate/near-duplicate cards don't reappear when the
cards are casually scattered (mixed rotation, imperfect spacing).

## Where this was found

Diagnosed 2026-08-13 while investigating a user report after deploying the
best-effort multi-card / hybrid-detection feature (commits introducing ADR
0005–0006, and later ADR 0008).

## Follow-up: the scale fix was not enough

The "Best" option above was implemented in `72cfb6e` (fractional corners plus
`_source_corners`), and ADR 0009 recorded it. The user still saw inflated card
counts and wrong crops afterwards, and confirmed the symptom predates the
orientation work in `c251322` — so it came in with `0e3ee31` and survived the
coordinate fix. Three causes remained:

1. **Asking the image AI for corner coordinates was itself the wrong idea.**
   Even at the correct scale the model's quadrilaterals were too imprecise to
   crop from, which is what produced the garbled cards. Vision models count
   objects far better than they localise them.
2. **Deduplication could never converge.** `next(...)` removed at most one
   local candidate per AI candidate, and `_iou > .5` on axis-aligned boxes did
   not fire when the local box bounded the text area while the AI box bounded
   the card outline. The two sets were added together instead of merged.
3. **`cv2.boundingRect` cannot describe a tilted card.** A card rotated on the
   desk gets an axis-aligned box whose ratio drifts toward 1.0 — failing the
   1.25–2.4 filter or swallowing its neighbour. `0e3ee31` also dropped the
   `candidates[:10]` cap that had been masking the local over-detection.

## Resolution

Fixed on branch `fix/card-detection-rotated-rects` (ADR 0010). The image-AI
detection pass was removed entirely; detection now runs on local contours as
rotated rectangles or four-point approximations, with containment-based
overlap collapsing, a candidate cap, and clockwise corner normalization before
perspective correction. Per-card orientation normalization (ADR 0008) was not
involved and is unchanged.
