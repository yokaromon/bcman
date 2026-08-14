---
status: superseded by ADR-0012
---

# Normalize card reading orientation before OCR

Every perspective-corrected Business Card receives an image-AI Reading Orientation check before OCR. The system uses only right-angle rotations, retains the orientation-corrected image separately, and appends rather than replaces OCR results after a user-confirmed correction so evidence remains traceable.
