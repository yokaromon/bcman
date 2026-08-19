# Organizations are provisioned in-app by a Provider Operator, and every account is claimed by Invitation

[ADR 0001](./0001-device-trust-and-totp.md) assumed Organizations would stay few and be provisioned by shell script, so the only way to create one was the CLI and the only cross-Organization actor was whoever had a shell on the server. Onboarding customers that way means a developer must be at a terminal for every sale, so Organization creation moves into the app behind a Provider Operator capability. At the same time, both existing ways of handing someone their credentials — an Administrator typing a colleague's initial password, and reading a TOTP secret off a screen to copy by hand — are replaced by a single-use Invitation the invitee completes themselves, because a password that one person chooses and tells to another is the weakest link in a design whose whole point is a second factor.

## Considered Options

**A third Role value was rejected in favour of a separate capability.** Every existing endpoint authorises with `require_admin` plus an `organization_id` equality check, and a Role that legitimately spans Organizations would make each of those checks ambiguous — exactly the kind of ambiguity that turns into an access-control bug. The Provider Operator is therefore a capability that gates only the provisioning endpoints; not one existing check was relaxed.

**A QR that logs the holder straight in was rejected.** It was the shortest path from "hand over a code" to "the new administrator is in", but a durable token that grants a session is a bearer credential that defeats the password and Registration Code that ADR 0001 exists to require. The Invitation instead grants only the right to *claim* an account, and dies the moment it is used.

**Login IDs became unique per Organization rather than globally.** Globally unique IDs need no login-form change, but the second customer can no longer be `admin` — a certainty, not a risk — so a Company Code was added to the login form and every Organization gets its own namespace.

## Consequences

An Invitation URL is, for the 24 hours it lives, enough to take possession of the account it names. For a new Organization that is nearly harmless because the Organization holds no Business Cards yet; for the re-invitation used to recover a locked-out User it is not, because that account already reaches real data, so recovery links are meant to be handed over in person or by a channel known to be trusted.

Because a Provider Operator can re-invite anybody, it can in principle become any User and read any Organization's data. This is not preventable by anything short of removing the recovery path, and whoever runs the server holds the database anyway; the protection is that every provisioning action is recorded where the affected Organization's Administrator can read it. The tenant boundary is enforced against mistakes and against ordinary Administrators, not against the operator.

A Company Code can never be changed, because every User of that Organization logs in with it. An Organization that renames itself keeps the code it was created with.

The CLI keeps `create-org`, since the first Provider Operator has to come from somewhere.
