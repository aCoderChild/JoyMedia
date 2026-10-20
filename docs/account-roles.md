# JoyMedia account roles

Assign roles on the Frappe User record. The portal shows the active role beside the account. Do not use a reviewer account for an internal team member or a paying client.

| Portal role | Frappe role | Workspace | Access controls |
| --- | --- | --- | --- |
| Administrator | System Manager (or Administrator) | Guided and advanced production tools | Manages users, reviewer grants, publication and feedback triage |
| Production team | JoyMedia Specialist | Guided and advanced production tools | Creates and edits own projects; cannot manage reviewer grants |
| Client | JoyMedia User | Guided creation, previews, scene/full-video history and comments | Own projects; no advanced editor, global media-library navigation or reviewer management |
| Reviewer | JoyMedia Reviewer, Website User | Only exact video versions published by an administrator | Comments and downloads independently controlled; own test projects only when explicitly enabled and within quotas |
| No role assigned | None of the above | Access-not-assigned screen | No portal creation or project navigation |

Administrators grant reviewer access at `/app/partner-access`. Adding a version publishes that exact version; newer versions remain private until added. End-to-end testing is an optional reviewer permission, not a client role or a promotion to the production team. Disabled accounts and grants cannot continue generation.

Reviewer and internal/client roles cannot be combined on one account. User validation rejects such combinations, and the portal fails closed for legacy conflicts. For non-reviewer accounts, the active role is Administrator, then Production team, then Client. Existing document ownership and Frappe permissions still apply; a role badge never grants document access. Use separate accounts when testing different roles.

Technical workflow and model administration stays under existing Frappe permissions. UI capabilities are returned by `joymedia.services.partners.get_access`; route guards and controls use the same capability flags. Reviewer publications, generation admission, quotas and feedback restrictions are additionally enforced by the backend.
