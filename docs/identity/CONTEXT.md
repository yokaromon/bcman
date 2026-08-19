# Identity

This context authenticates the people who use the system and defines the tenant structure — Organization and Group — that scopes what they can see. It owns login, device trust, and role, and hands other contexts nothing but a User's identity and the Group/Organization they belong to.

## Language

**Organization**:
The strict tenant boundary. Data belonging to one Organization is never accessible from another, and each Organization independently chooses its Sharing Mode.
_Avoid_: Tenant, company, account

**Company Code**:
The short, human-typed identifier that names one Organization at login, unique across the whole system and fixed for the Organization's lifetime. It exists so that each Organization can choose its own login IDs — every Organization wants an `admin` — and it is never changed after creation because every one of that Organization's Users logs in with it.
_Avoid_: Tenant ID, slug, organization key

**Sharing Mode**:
An Organization-wide setting, chosen by its Administrator, that is either isolated (a User sees only the Business Cards belonging to the Groups they're a member of) or shared (a User sees the Business Cards of every Group in the Organization).
_Avoid_: Visibility setting, permission mode

**Group**:
A subdivision of one Organization that a User can belong to, and that a Business Card belongs to. A User may belong to more than one Group in their Organization; in isolated Sharing Mode, what they see is the union of those Groups' Business Cards.
_Avoid_: Team, department

**User**:
An account that can log in, identified by a login ID that is unique within its Organization and reached through that Organization's Company Code. It belongs to exactly one Organization for its lifetime and to one or more Groups within it. Created only by an Administrator or the Provider Operator — there is no self-registration — and it exists in an unactivated state, unable to log in, until its Invitation is completed.
_Avoid_: Account, member

**Role**:
Either Administrator or General User. An Administrator manages every User, Group, and Trusted Device within their own Organization; a General User has no management capability. Neither role reaches outside its own Organization; the only capability that does is the Provider Operator's, and it is deliberately not a Role.
_Avoid_: Permission level, access level

**Provider Operator**:
The single account that operates the service itself, able to create Organizations and to issue an Invitation to any User in any of them. It is a capability held alongside an ordinary Role, not a Role of its own, and it grants no access whatsoever to Business Cards or Contacts — the tenant boundary is unchanged for every existing endpoint. Because issuing an Invitation resets credentials, the Provider Operator can in principle reach tenant data by becoming a User; every action it takes is therefore recorded for the affected Organization to read.
_Avoid_: Superadmin, root, cross-tenant administrator

**Invitation**:
The single-use, time-limited link by which a User first takes possession of their account, or takes it back after losing their credentials. Completing it requires the invitee to choose their own password and to prove their Registration Code works by entering one; on completion the Invitation dies, every Trusted Device the User previously had is revoked, and the Device completing it becomes Trusted. It is the only way a User's password is ever set, so no password is ever chosen by one person and told to another.
_Avoid_: Password reset link, activation token, magic link

**Trusted Device**:
A browser that has already proven its User's identity with a Registration Code, remembered for 90 days so routine logins don't ask for one again. An Administrator can see a User's Trusted Devices and revoke one immediately, independent of the 90-day expiry.
_Avoid_: Remembered device, known device

**Registration Code**:
A time-based one-time code (TOTP) that proves a not-yet-Trusted Device belongs to the User logging in from it. Enrolled by the User while completing their Invitation, and replaced only by completing another one.
_Avoid_: 2FA code, auth key

**Office Network**:
The one fixed-IP network, allow-listed independently of Organization, from which a login is treated as if the Device were already trusted. It exists because requiring a Registration Code on every office login would add friction without adding security for a location that's already physically controlled.
_Avoid_: Trusted IP, allowed network
