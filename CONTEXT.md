# Business Card Management

This context manages scanned business cards from photo upload through human-reviewed contact registration. It preserves each Business Card and its recognition results for review, while treating the uploaded Photo as temporary source material.

## Language

**Photo**:
One uploaded source image that may contain one or more business cards. It is deleted by default when the user completes review, unless the user selects the off-by-default option to retain it at completion; its remaining Business Cards stay reviewable after deletion.
_Avoid_: Card image, original card

**Business Card**:
One detected physical card belonging to a Photo, together with its derived images and recognition state. It stays the same Business Card even when its image is later replaced by a Card Retake, so the Photo it belongs to records where the card was first found rather than where its current image came from.
_Avoid_: Contact, scan

**Extractable Business Card**:
A card-shaped physical object in a Photo whose four corners are inside the image and whose outline a human reviewer can identify. Its side, reading orientation and text legibility do not affect eligibility; an object with any off-frame or indeterminate corner is not extractable.
_Avoid_: Readable card, front side, partial card

**Contact**:
The editable, structured information extracted from one Business Card; it becomes registered only after confirmation.
_Avoid_: Business card data, person

**Confirmed Contact**:
A Contact explicitly accepted by a user as the registered record.
_Avoid_: Auto-registered contact

**Recognition Result**:
OCR text blocks and structured-field candidates derived from a Business Card, which remain reviewable evidence rather than confirmed data. Re-recognition after a Reading Orientation correction adds a new result without replacing the earlier one. Only the reading that settles the Reading Orientation becomes a Recognition Result; the rotations tried and discarded are kept as processing history instead.
_Avoid_: Contact, final result

**Best-effort Recognition**:
Recognition that queues every detected Business Card from a Photo without rejecting it solely for the number of cards. Twelve cards is the Card Detection and Card Extraction guarantee; larger sets may take longer, be extracted only in part or need more review. Card Detection still caps how many candidates one Photo may yield as a cost safety valve.
_Avoid_: Maximum-card limit, batch rejection

**Extraction Capacity**:
A Photo containing one to twelve Extractable Business Cards is within the guaranteed range of Card Detection and Card Extraction and must yield exactly one Business Card per physical object. A Photo containing thirteen or more is processed on a best-effort basis. Extraction Ground Truth itself has no card-count ceiling: a human reviewer records every Extractable Business Card even when the Photo is outside the guaranteed range.
_Avoid_: Approximate maximum, Recognition limit

**Extraction Ground Truth**:
The human-reviewed set of Extractable Business Cards in a Photo and the four source-image corners of each one.
_Avoid_: Detector output, estimated corners

**Extraction Acceptance**:
A Photo passes extraction evaluation only when its detected count exactly matches its Extraction Ground Truth and every matched quadrilateral has an intersection-over-union of at least 0.90. Results are assessed per Business Card rather than accepted by an average score.
_Avoid_: Visual spot check, average accuracy

**Detection Failure**:
The outcome in which no Extractable Business Card candidate is found in a Photo. It creates no Business Card or Card Extraction output; the user may retake the Photo or supply the missing card's four corners manually.
_Avoid_: OCR failure, unreadable card

**Manual Card Addition**:
A user-created Business Card whose four corners are supplied by the user after Card Detection missed it, including after Detection Failure. It is perspective-corrected and immediately queued for independent recognition.
_Avoid_: Retaking a photo, rectangular crop

**Card Detection**:
The process that identifies every Extractable Business Card in a Photo and locates its four source-image corners. Within Extraction Capacity it yields exactly one candidate per physical card; candidates are presented top row first and left to right within a row.
_Avoid_: OCR, rectangular cropping

**Card Extraction**:
The creation of one perspective-corrected image for each detected physical Business Card from its four corners. It preserves the photographed reading orientation and excludes Reading Orientation and OCR.
_Avoid_: Rectangular crop, orientation correction, recognition

**Reading Orientation**:
The rotation of 0, 90, 180, or 270 degrees that presents the printed content of a perspective-corrected Business Card upright for recognition. It defaults to 0 degrees, i.e. however the card was photographed, and is never guessed automatically. The user can correct it in 90-degree steps, previewing before it is committed and re-recognised; a corrected orientation is read as given, never re-derived. The orientation-corrected image is retained separately from the perspective-corrected image.
_Avoid_: Card angle, image rotation, automatic orientation detection

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

**Card Owner**:
The User who exchanged a Business Card in person and owns the resulting relationship, distinct from whoever operated the scanning. Defaults to the User performing Batch Registration but can be reassigned per Contact, to cover proxy scanning (e.g. an assistant registering cards on a salesperson's behalf).
_Avoid_: Registrant, uploader, owner

**Card Retake**:
A fresh photograph of one Business Card, taken to replace an image that is blurred, shadowed or badly cropped. The user approves the cropped result before it is committed, then chooses whether to keep the confirmed Contact as it is or re-read it from the new image. It replaces the Business Card's corrected images only; the earlier generation is not kept, and the card's place in its Photo is unchanged.
_Avoid_: Re-upload, rescan, new photo

**Ledger**:
The searchable view of every Confirmed Contact a user may see, independent of which Photo each one came from. It is where registered information is corrected after the fact, and it never shows Contacts that were never confirmed — those remain reachable only by working back through their Photo.
_Avoid_: Directory (reserved for Person/Company aggregation), history, contact list

**Exchanged At**:
The date a Business Card was actually exchanged in person, as distinct from when its Photo was uploaded. Defaults to the Photo's upload date at Batch Registration time but can be corrected by the Card Owner, to cover batch-scanning a stack of cards well after the events they came from.
_Avoid_: Registered at, created at, meeting date
