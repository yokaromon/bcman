# Business Card Management

This context manages scanned business cards from photo upload through human-reviewed contact registration. It preserves both source evidence and recognition results so they can be reviewed or reanalysed.

## Language

**Photo**:
One uploaded source image that may contain one or more business cards.
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
OCR text blocks and structured-field candidates derived from a Business Card, which remain reviewable evidence rather than confirmed data.
_Avoid_: Contact, final result
