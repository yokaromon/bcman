# Directory

This context turns registered contacts into a durable relationship graph: who inside the Organization has met whom outside it, and at which Company. It consumes Confirmed Contacts from [Business Card Management](../../CONTEXT.md) by ID and never merges records automatically — every aggregation is a suggestion a User confirms.

## Language

**Person**:
A deduplicated real-world individual, built by merging one or more Confirmed Contacts that a User has confirmed represent the same person. Merging is never automatic: the system only suggests candidates, and a Person forms the first time a User accepts one. Candidates are surfaced by an exact email match (strong signal) or by a kana-normalized match of person name plus company name (weaker signal, since a Business Card often carries no personal email). Its aggregation is scoped to what a User can see under their Organization's Sharing Mode — a User in isolated mode only sees merge candidates from their own Groups, so the same real individual can exist as separate Person records in different Groups.
_Avoid_: Contact, person master record

**Company**:
A deduplicated real-world organization, built the same way as a Person: merge candidates are suggested, never merged automatically, and scoped to what a User can see under their Organization's Sharing Mode. Candidates are surfaced by a kana-normalized match of company name, or by a matching website domain (stronger, since a Business Card's company name has more spelling and legal-suffix variation than its website).
_Avoid_: Organization (reserved for the Identity tenant boundary), business, employer

**Touch History**:
The Exchanged-At-ordered timeline of a Person's Confirmed Contacts, one entry per Confirmed Contact merged into that Person — there is no touch that exists independently of a Business Card exchange. Each entry keeps the Company Name and Card Owner exactly as they were on its own Confirmed Contact, so a Person's job change shows up as a change partway through their history rather than being rewritten into their current Company.
_Avoid_: Meeting log, interaction history, activity feed

**Split**:
The reversal of a mistaken merge: detaching one Confirmed Contact from its Person or Company and giving it back an independent Person or Company of its own. It undoes exactly one merge decision rather than dissolving the whole record, so the remaining Confirmed Contacts stay merged together.
_Avoid_: Unmerge, delete person, undo

**Merge Candidate**:
A suggested pairing between a newly Confirmed Contact and an existing Person or Company, surfaced by the matching signals above. It is computed exactly once, at the moment the Confirmed Contact is created, by comparing it against existing Persons/Companies — never by periodically re-scanning already-resolved pairs. It appears as a light-touch indicator right where the Contact was just registered, but is resolved — accepted or dismissed — from a dedicated review screen rather than in that moment, so registering many cards in a row is never interrupted. A dismissal is not remembered: because each pair is only ever compared once, the same Merge Candidate cannot resurface on its own — only editing the Confirmed Contact's matched fields (e.g. its email) triggers a fresh comparison. That fresh comparison only proposes candidates: it never moves a Contact out of the Person or Company it already belongs to, so correcting a company name does not re-file the Contact under the new Company — that is what Split is for.
_Avoid_: Duplicate warning, suggestion
