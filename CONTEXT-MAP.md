# Context Map

## Contexts

- [Business Card Management](./CONTEXT.md) — manages scanned business cards from photo upload through human-reviewed contact registration
- [Identity](./docs/identity/CONTEXT.md) — authenticates Users and defines the Organization/Group tenant structure they belong to

## Relationships

- **Identity → Business Card Management**: Identity owns Organization, Group, and User; Business Card Management scopes every Photo and Business Card to the Organization and Group of the User who created it, and references Users and Groups by ID only
