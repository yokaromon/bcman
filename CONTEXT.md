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
OCR text blocks and structured-field candidates derived from a Business Card, which remain reviewable evidence rather than confirmed data. A Reading Orientation correction does not change an existing result or trigger OCR; only an explicit re-recognition adds a new result without replacing the earlier one. Orientation probes that are tried and discarded remain processing history rather than Recognition Results.
_Avoid_: Contact, final result

**Recognition Fingerprint**:
The identity of a recognition-stage input, composed from the oriented-image SHA-256, Reading Orientation, local detector model version, managed ykr model identifier, prompt version and JSON Schema version. Normal resume reuses a successful result with the same fingerprint; explicit user re-recognition bypasses reuse and adds a new result without overwriting earlier results or user-edited values.
_Avoid_: Image filename, mutable cache key

**Recognition Release**:
An immutable, explicitly versioned combination of Card Extraction, Reading Orientation and Text Region Detection models, managed ykr model, prompts, JSON Schemas, normalization rules and decision thresholds. Floating model aliases and automatic model updates are forbidden; any component change, including additional training, creates a new candidate that must pass development regression and every Recognition Pipeline Acceptance gate before production promotion.
_Avoid_: Latest model, in-place prompt edit

**Recognition Pipeline V2 Pilot**:
The feature-flagged production introduction of a Recognition Release after pickup acceptance. It starts disabled, applies only to administrator-selected new images, never reprocesses existing registered Business Cards automatically and never lets V1 and V2 update the same Contact; V1 remains available for rollback until V2 is explicitly declared stable and made the default for new processing.
_Avoid_: Big-bang migration, dual write

**Managed Recognition Privacy**:
The data-minimizing operating boundary for `app.ykr.ltd`: ordinary OCR requests never persist Business Card images, transcriptions, structured values or request bodies in access or error logs. Operational logs retain only request identifier, time, pinned model version, HTTP status and duration; training data enters through a separately authorized, human-selected path rather than being harvested from runtime logs.
_Avoid_: API-log training set, request-body diagnostics

**Best-effort Recognition**:
Recognition that queues every detected Business Card from a Photo without rejecting it solely for the number of cards. Twelve cards is the Card Detection and Card Extraction guarantee; larger sets may take longer, be extracted only in part or need more review. Card Detection still caps how many candidates one Photo may yield as a cost safety valve.
_Avoid_: Maximum-card limit, batch rejection

**Extraction Capacity**:
A Photo containing one to twelve Extractable Business Cards is within the guaranteed range of Card Detection and Card Extraction and must yield exactly one Business Card per physical object. A Photo containing thirteen or more is processed on a best-effort basis. Extraction Ground Truth itself has no card-count ceiling: a human reviewer records every Extractable Business Card even when the Photo is outside the guaranteed range.
_Avoid_: Approximate maximum, Recognition limit

**Extraction Ground Truth**:
The human-reviewed set of Extractable Business Cards in a Photo and the four source-image corners of each one. Every annotated card has a stable identity independent of detector order, shared by its Orientation, OCR Transcription and Contact Field Ground Truth.
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
The rotation of 0, 90, 180, or 270 degrees that presents the printed content of a perspective-corrected Business Card upright. It may be proposed once for each new Card Extraction, but a user may correct it in 90-degree steps or accept the photographed orientation; OCR re-recognition never re-derives it, and a user-confirmed orientation is never silently changed. Correcting it does not itself rerun OCR, and the orientation-corrected image is retained separately from the perspective-corrected image.
_Avoid_: Card angle, image rotation, forced automatic orientation

**Orientation Uncertain**:
The state in which automatic Reading Orientation cannot confidently choose among 0, 90, 180 and 270 degrees. The Business Card remains as photographed while OCR and registration continue; the user may rotate it later or accept it unchanged rather than being forced to resolve the uncertainty.
_Avoid_: Default orientation, rotation failure, low-confidence rotation

**Orientation Decision**:
The provenance of the current Reading Orientation, recorded separately from its rotation value as auto-confirmed, uncertain or user-confirmed. A user's rotation or explicit acceptance makes the decision user-confirmed and prevents later automatic replacement.
_Avoid_: Rotation angle, OCR status, implicit default

**Orientation Ground Truth**:
The human-reviewed acceptable Reading Orientations for one extracted Business Card, expressed as one or more right-angle rotations, or as indeterminate when no direction is objectively preferable. It never forces a single answer onto a rotationally ambiguous card.
_Avoid_: Assumed upright direction, forced orientation label

**Orientation Feedback Candidate**:
A disagreement between an automatic orientation proposal and a later user-confirmed Orientation Decision that may be selected for human annotation. It is neither Orientation Ground Truth nor a training label until reviewed, because user rotation can express preference or error rather than an objective reading direction.
_Avoid_: User label, automatic training example

**Recognition Feedback Candidate**:
A user correction to managed OCR text or a Structured Field Candidate that may be reviewed for additional training. Like Orientation Feedback Candidate, it never becomes ground truth or a training label automatically; an authorized reviewer must compare it with the source Business Card and explicitly accept it into the managed training set.
_Avoid_: Runtime training label, implicit user consent

**Additional Training**:
Conditional model adaptation considered only after a pinned pretrained baseline has been measured and failure analysis shows that training is an appropriate remedy for an unmet Acceptance gate. It may use development data and human-approved feedback candidates, but never the fixed holdout for training, prompt design, threshold calibration or model selection; the resulting artifact is a new Recognition Release.
_Avoid_: Train-first optimization, holdout tuning

**Orientation Acceptance**:
The evaluation of automatic Reading Orientation against Orientation Ground Truth, reporting confident accuracy and the Orientation Uncertain rate separately for human-cornered reference crops and actual Card Extraction outputs. Its initial targets are at least 99 percent accuracy among confident decisions, no more than 15 percent uncertainty among cards with an objectively determinable direction and at most six seconds of warm CPU processing per card while disclosing cold model startup separately; production promotion requires a fixed holdout of at least 300 unique unseen Business Cards rather than counting rotations of one design as independent cards.
_Avoid_: Average confidence, accuracy without uncertainty coverage

**OCR Transcription Ground Truth**:
The human-reviewed spatial lines of Transcribable Text on one Business Card, each retaining its region, exact transcription and printed or handwritten source independently of how it is assigned to Contact fields. Machine-generated regions or text may be annotation drafts, but become ground truth only after human verification; an unreadable region is marked illegible rather than guessed.
_Avoid_: OCR output, structured contact data

**Text Region Detection**:
Local detection of polygonal regions and reading-order candidates that may contain Transcribable Text. It supplies geometry to managed OCR but does not determine the authoritative transcription; the managed ykr service returns ordered text, printed-or-handwritten source and legibility without inventing pixel coordinates, and the persisted alignment keeps both forms of evidence traceable.
_Avoid_: OCR transcription, AI-estimated coordinates

**OCR Line Alignment**:
The persisted association between a local Text Region and a managed ykr transcription line. A line found only by ykr is retained with a null region, a region found only locally is retained with null text, and both use `alignment_status: unmatched` rather than being forced together. Unmatched managed text remains available to Contact structuring, while any field supported only by such text carries a Review Flag.
_Avoid_: Forced nearest region, discarded unmatched text

**Transcribable Text**:
Human-legible printed or handwritten text physically on a Business Card, including readable text in a logo. It excludes encoded QR or barcode payloads and text introduced from outside the card by extraction error.
_Avoid_: Guessed text, code payload, neighbouring-card text

**Contact Field Ground Truth**:
The human-reviewed expected value of every registerable Contact field that is explicitly supported by Transcribable Text on one Business Card, using null for an absent value—including an unprinted name reading—and a distinct unreadable state for a present but illegible value. It is evaluated separately from OCR Transcription Ground Truth so recognition errors and structuring errors remain distinguishable.
_Avoid_: Raw transcription, inferred contact

**Structured Field Candidate**:
A proposed Contact field represented by its value, semantic state and the identifiers of the managed OCR lines that support it. `present` requires a non-null value and at least one valid source line; `absent` requires a null value and no source lines; `unreadable` requires a null value and at least one source line, may keep a tentative transcription only as `candidate_value`, and always carries a Review Flag. Every multi-line value identifies all contributing lines. A response that violates these invariants is structurally invalid and consumes the Contact-structuring retry budget; once that budget is spent it is handed to Response Repair rather than discarded whole.
_Avoid_: Unattributed AI value, confirmed Contact field

**Contact Structuring**:
The managed transformation of a validated OCR result into Structured Field Candidates. Its request contains line identifiers, transcription, reading order, local geometry, printed-or-handwritten source and legibility, but never resends the Business Card image; it may select and normalize evidence but cannot introduce text absent from the supplied OCR lines.
_Avoid_: Second image recognition, Contact confirmation

**Field Normalization**:
The deterministic local derivation of a comparison value from a Structured Field Candidate's source-preserving `display_value`, such as removing separators from a telephone number. The derived `normalized_value` supports validation, search and evaluation but never replaces the displayed or registered spelling and formatting; managed AI does not perform this normalization.
_Avoid_: AI correction, display-value rewriting

**Field Validation**:
Deterministic local checks applied after Field Normalization, such as email-address, telephone-number, URL and postal-code format checks. A failed check preserves the source `display_value` and evidence, adds a Review Flag and does not retry or reject an otherwise structurally valid Contact-structuring response.
_Avoid_: AI retry for bad print, discarded candidate

**Evidence Validation**:
A deterministic check that a Structured Field Candidate can be derived from the managed OCR lines it cites. A non-derivable value is retained only as a review candidate with `evidence_status: unsupported`, always carries a Review Flag, cannot be registered without user edit or explicit acceptance, does not consume an API retry, and counts as a hallucinated or unsupported value in evaluation.
_Avoid_: Trusted line identifier, silent hallucination

**Response Repair**:
The deterministic local reshaping of a Contact-structuring response that remains structurally invalid after the retry budget is exhausted. It restores omitted keys, coerces value types, drops unknown source line identifiers and resolves a single field's contradictory state, so that one malformed field never discards the correct fields beside it. It runs only after retries are spent, never invents a value or a source line, and every repaired field carries a Review Flag identifying it as repaired. A repaired response is evaluated as a failure of the managed structuring step even when its fields are usable.
_Avoid_: Relaxed schema, silent acceptance

**Format Baseline**:
The deterministic local extraction of only those Contact fields whose format alone identifies them—email address, website, postal code, telephone, fax and mobile—from OCR lines already obtained. It is the floor used when Contact Structuring fails outright, so a Business Card yields its format-certain fields instead of nothing. It never proposes a field that format cannot determine, such as a person or company name, every field it proposes carries a Review Flag, and a card served by it counts as a Contact Structuring failure in evaluation.
_Avoid_: Local structuring engine, AI replacement

**Contact Note**:
Explicit supplementary printed text or a human-written memo physically present on a Business Card that does not belong in another Contact field. It is never an AI summary, inferred context or a catch-all for leftover OCR text.
_Avoid_: AI summary, unmatched OCR, inferred note

**Contact Field Acceptance**:
The field-by-field evaluation against Contact Field Ground Truth, reporting normalized exact match and missed present values separately from values hallucinated for absent fields, unsupported Structured Field Candidates and unreadable values routed to Review Flags. Its initial targets are at least 99 percent normalized exact match for present person-name, company-name, telephone, mobile, fax, email, website and postal-code values; at least 95 percent normalized exact match for present addresses, departments, positions and printed name readings; at most 5 percent normalized character error rate for present Contact Notes; zero hallucinated values in evaluated absent fields; zero accepted non-null values without valid source-line evidence; and 100 percent Review Flag routing for evaluated unreadable fields with the sample count disclosed. It never combines absence-heavy and presence-only cases into one accuracy that can be inflated by returning null.
_Avoid_: Overall field accuracy, OCR character accuracy

**Recognition Pipeline Acceptance**:
The production-promotion evaluation of one frozen Recognition Release on a fixed holdout of at least 300 unique unseen Business Cards carrying Extraction, Orientation, OCR Transcription and Contact Field Ground Truth. Every pipeline stage must satisfy its own acceptance criteria; final OCR and Contact structuring use the user-managed `app.ykr.ltd` service and must complete within 30 seconds at the 95th percentile, count any 90-second timeout as failure and never let one card stop its peers. Card Extraction and Reading Orientation must run without network access, but full Recognition Pipeline completion requires the managed service. Strength in another stage never promotes a failing pipeline.
_Avoid_: End-to-end average, development regression set

**OCR Acceptance**:
The evaluation of OCR against OCR Transcription Ground Truth, reporting local Text Region Detection, managed transcription alignment, strict character error rate and normalized character error rate separately. Normalized scoring unifies agreed Unicode, whitespace and punctuation variants without replacing the strict measure of transcription fidelity; its initial acceptance target for printed text is at most 2 percent normalized character error rate.
_Avoid_: Single OCR score, field extraction accuracy

**Retry Required**:
The state of a detected Business Card whose managed OCR or Contact structuring stage still fails after one automatic retry of that stage. A transport error, timeout, JSON Schema violation, missing required key or invalid value type consumes the stage's retry budget. OCR and Contact structuring each allow at most two managed requests, for at most four per card; a successful OCR result is reused when only structuring is retried. The card remains a review candidate and can be retried independently without interrupting peers; processing never loops indefinitely or switches automatically to local OCR.
_Avoid_: Photo failure, discarded card

**Review Flag**:
An indication on an extracted Contact field that needs user confirmation, determined from recognition confidence, applicable value-format validation or evidence that the source value is unreadable. An unreadable candidate may be shown but is never automatically confirmed; the flag is resolved when the user edits the field or explicitly accepts its value or absence.
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
A fresh photograph of one Business Card, taken to replace an image that is blurred, shadowed or badly cropped. The user approves the cropped result before it is committed; the replacement forms a new Card Extraction with one new automatic Reading Orientation proposal, while the user chooses whether to keep the confirmed Contact or explicitly re-read it. The earlier image generation is not kept, and the card's place in its Photo is unchanged.
_Avoid_: Re-upload, rescan, new photo

**Ledger**:
The searchable view of every Contact a user may see, confirmed or not, independent of which Photo each one came from. It is where registered information is corrected after the fact. An unconfirmed Contact is shown as unconfirmed on its own row and can be narrowed away by an explicit filter, but is never hidden by default: a captured card that cannot be found reads as a system fault rather than as an unfinished task, and silently withholding it is what lets the confirmation step be forgotten. Ordering falls back to the Photo's capture date while Exchanged At is still unset, so unconfirmed entries stay in view instead of sinking beneath every confirmed one. Only confirmed Contacts reach the Directory.
_Avoid_: Directory (reserved for Person/Company aggregation), history, contact list, confirmed-only view

**Exchanged At**:
The date a Business Card was actually exchanged in person, as distinct from when its Photo was uploaded. Defaults to the Photo's upload date at Batch Registration time but can be corrected by the Card Owner, to cover batch-scanning a stack of cards well after the events they came from.
_Avoid_: Registered at, created at, meeting date
