# Device trust with TOTP, gated by a single Office Network allow-list

Business cards carry personal data, so login security matters, but requiring a second factor on every access from a phone outside the office was rejected as too much friction for daily use. Instead: a login from the Office Network's fixed IP, or from a Device already Trusted, needs only User ID and password; a login from any other network on a not-yet-Trusted Device needs a TOTP Registration Code as well, after which that Device is remembered for 90 days. The Office Network allow-list is a single system-wide range enforced at nginx, not a per-Organization setting stored in the database — the number of Organizations is expected to stay small and be provisioned by shell script (see [Identity](../CONTEXT.md)), so a config-file allow-list is easier to maintain than a UI nobody but ops would use, and a per-Organization allow-list would anyway be awkward to enforce from a single nginx in front of one app.

## Considered Options

TOTP was chosen over an administrator-issued one-time code for the Registration Code. An admin-issued code keeps registration under tighter administrator control and needs no authenticator-app setup, but it makes every new-device registration — a new phone, a cleared browser, a trip — wait on an administrator being reachable, which is exactly the friction this design exists to avoid. TOTP is self-service after one QR-code setup at account creation, and the only administrator involvement left is resetting it if a phone is lost.

## Consequences

A Trusted Device is bound to a browser via a persistent cookie, not to a physical device — clearing cookies or switching browsers looks like a new, untrusted device and asks for the Registration Code again. Administrators can revoke a Trusted Device immediately (for a lost phone) without waiting for its 90-day expiry.
