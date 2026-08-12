# Organization-wide group sharing mode

An Organization is the strict tenant boundary: its data is never accessible across Organizations. Its administrator selects one Organization-wide sharing mode: **isolated**, which limits standard users to the data of the Group(s) they belong to, or **shared**, which allows access across all Groups in that Organization. This avoids per-user exceptions while allowing each Organization to choose its collaboration model.

A User can belong to more than one Group within their Organization (see [Identity](../identity/CONTEXT.md)). In isolated mode, "the data of the Group(s) they belong to" is the union across all of a User's Groups, not a single Group — isolated only means "never another Organization's or a foreign Group's data," not "at most one Group."
