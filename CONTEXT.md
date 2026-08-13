# Business Card Management

This context manages scanned business cards from photo upload through human-reviewed contact registration. It preserves each Business Card and its recognition results for review, while treating the uploaded Photo as temporary source material.

## Language

**Photo**:
One uploaded source image that may contain one or more business cards. It is deleted by default when the user completes review, unless the user selects the off-by-default option to retain it at completion; its remaining Business Cards stay reviewable after deletion.
_Avoid_: Card image, original card

**Business Card**:
One detected physical card belonging to a Photo, together with its derived images and recognition state.
_Avoid_: Contact, scan

**Contact**:
The editable, structured information extracted from one Business Card; it becomes registered only after confirmation.
_Avoid_: Business card data, person

**Confirmed Contact**:
A Contact explicitly accepted by a user as the registered record.
_Avoid_: Auto-registered contact

**Recognition Result**:
OCR text blocks and structured-field candidates derived from a Business Card, which remain reviewable evidence rather than confirmed data. Re-recognition after a Reading Orientation correction adds a new result without replacing the earlier one.
_Avoid_: Contact, final result

**Best-effort Recognition**:
Recognition that queues every detected Business Card from a Photo without rejecting it solely for the number of cards. Eight cards is the quality target; larger sets may take longer or need more review. Card Detection still caps how many candidates one Photo may yield, so a Photo crowded well beyond the target is recognised only in part.
_Avoid_: Maximum-card limit, batch rejection

**Detection Failure**:
The outcome in which no Business Card candidate is found in a Photo. The whole Photo then becomes a single low-confidence Business Card rather than ending the attempt, because a single card filling the frame leaves no detectable outline. The user is asked to retake the Photo only when that candidate cannot be recognised either.
_Avoid_: OCR failure, unreadable card

**Manual Card Addition**:
A user-created Business Card in a Photo where at least one card was detected automatically. The user supplies its four corners so it can be perspective-corrected and immediately queued for independent recognition.
_Avoid_: Retaking a photo, rectangular crop

**Card Detection**:
The process that identifies Business Card candidates and their four corners in a Photo, using local image contours only. Each candidate is a rotated rectangle or a four-point approximation of one contour, kept when its proportion and size are card-like. A candidate largely contained in a larger one is treated as the same physical card and dropped, and the number of candidates is capped as a cost safety valve. Corners are ordered clockwise from the top-left, and candidates are presented top row first, left to right within a row.
_Avoid_: OCR, rectangular cropping

**Reading Orientation**:
The rotation of 0, 90, 180, or 270 degrees that presents the printed content of a perspective-corrected Business Card upright for recognition. Every perspective-corrected Business Card receives an image-AI orientation check before OCR, and the user can correct it in 90-degree steps before re-recognition. An unknown orientation leaves the image unrotated and is surfaced for user correction; manual rotation previews before it is committed and re-recognised. The orientation-corrected image is retained separately from the perspective-corrected image.
_Avoid_: Card angle, image rotation

**Retry Required**:
The state of a detected Business Card whose OCR or structuring attempt still fails after one automatic retry. It remains a review candidate and can be retried independently without interrupting other cards.
_Avoid_: Photo failure, discarded card

**Review Flag**:
An indication on an extracted Contact field that needs user confirmation, determined from recognition confidence together with applicable value-format validation. It is shown to the user without exposing a raw confidence score and is resolved when the user edits that field or explicitly accepts it as blank.
_Avoid_: Required field, OCR failure

**Recognition Progress**:
The count of Business Cards in a Photo whose recognition has completed, shown alongside the total detected candidates while the remaining cards continue processing. In-progress cards appear in the candidate list but cannot be selected for Batch Registration.
_Avoid_: Batch completion, processing percentage

**Batch Registration**:
The explicit confirmation that registers only the user-selected Contact candidates from one Photo whose Review Flags are resolved. Candidates are selected from a thumbnail-and-status list; it never deduplicates or merges candidates automatically.
_Avoid_: Auto-registration, automatic deduplication
