# Selected local projects restored to GPU deployment

The public GPU demo uses its own database and Client account. Changing its
public tunnel does not synchronize the local development site's projects.
On 29 October 2026 (Asia/Ho_Chi_Minh), the following selected local edits were
copied into the deployed Client account:

| Project | Local video | Source edit | Deployed edit |
| --- | --- | --- | --- |
| Shera | 14 | PRJ-02558 | LOCAL-PRJ-02558 |
| Shera | 33 | PRJ-02586 | LOCAL-PRJ-02586 |
| T-Shirt AUNTIE | 5 | PRJ-02563 | LOCAL-PRJ-02563 |

The deployed families are `LOCAL-PRJ-02501` and `LOCAL-PRJ-02559`. Working edits
are Shera 33 and fashion 5. Source projects and files were left unchanged.
The original numbers are stored in the optional, read-only, non-copying
`source_video_number` field so selective imports keep their original identity.
Ordinary local projects keep their existing numbering behavior.

The transfer restored project references, selected storyboards, authored scene
timing, timeline clips, output assets, and linked generation provenance. It
copied 124 unique media files (186,160,950 bytes), verified by SHA-256. Imported
document identifiers use a `LOCAL-` prefix to avoid existing ID collisions.
Existing incomplete job records were cancelled rather than enqueued. Historical
source project stubs required by provenance are archived and administrator-owned;
they do not appear in the Client's project list or trash. Historical container
shots are marked removed so only the three requested videos appear on shelves.
No generation was started by the transfer, and no source approval was attributed
to the deployed Client.

Database backup, source manifest, media archive, import script, pre-change API
and schema files, and completion report are retained on the GPU under
`/home/ubuntu/joymedia-demo-staging/selected-project-transfer-20261029`.
The database backup is `database-before.sql.gz`. The importer used one database
transaction and checked all restored document links before committing.

Verification used the deployed Client login over the public HTTPS hostname:

- Exactly two project cards, with two Shera videos and one fashion video.
- Shelf numbers 14, 33, and 5, each pointing to the intended original MP4.
- All three project workspaces open successfully.
- All three videos support authenticated HTTP 206 playback with `video/mp4`.
- Local video numbering remained unchanged; the changed API passes Ruff.
