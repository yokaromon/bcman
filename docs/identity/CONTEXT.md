# Identity

This context authenticates the people who use the system and defines the tenant structure — Organization and Group — that scopes what they can see. It owns login, device trust, and role, and hands other contexts nothing but a User's identity and the Group/Organization they belong to.

## Language

**Organization**:
The strict tenant boundary. Data belonging to one Organization is never accessible from another, and each Organization independently chooses its Sharing Mode.
_Avoid_: Tenant, company, account

**Sharing Mode**:
An Organization-wide setting, chosen by its Administrator, that is either isolated (a User sees only the Business Cards belonging to the Groups they're a member of) or shared (a User sees the Business Cards of every Group in the Organization).
_Avoid_: Visibility setting, permission mode

**Group**:
A subdivision of one Organization that a User can belong to, and that a Business Card belongs to. A User may belong to more than one Group in their Organization; in isolated Sharing Mode, what they see is the union of those Groups' Business Cards.
_Avoid_: Team, department

**User**:
An account that can log in, belonging to exactly one Organization for its lifetime and to one or more Groups within it. Created only by an Administrator — there is no self-registration.
_Avoid_: Account, member

**Role**:
Either Administrator or General User. An Administrator manages every User, Group, and Trusted Device within their own Organization; a General User has no management capability. There is no role that spans Organizations.
_Avoid_: Permission level, access level

**Trusted Device**:
A browser that has already proven its User's identity with a Registration Code, remembered for 90 days so routine logins don't ask for one again. An Administrator can see a User's Trusted Devices and revoke one immediately, independent of the 90-day expiry.
_Avoid_: Remembered device, known device

**Registration Code**:
A time-based one-time code (TOTP) that proves a not-yet-Trusted Device belongs to the User logging in from it. Issued once per User at account creation; an Administrator can reissue one if it's lost.
_Avoid_: 2FA code, auth key

**Office Network**:
The one fixed-IP network, allow-listed independently of Organization, from which a login is treated as if the Device were already trusted. It exists because requiring a Registration Code on every office login would add friction without adding security for a location that's already physically controlled.
_Avoid_: Trusted IP, allowed network
