# Tool risk matrix

Risk is a property of the *tool*, not the prompt. The gateway also applies dynamic
risk where required (see `messaging_reply`).

| Tool | Tier | Approval | Scopes | Rate/min | Dry run | Notes |
|---|---|---|---|---|---|---|
| `health_status` | LOW | no | `read:health` | 60 | — | never returns secrets; works while the kill-switch is on |
| `set_light` | LOW | no | `home:write` | 30 | yes | entity allowlist enforced by the schema validator |
| `get_state` | LOW | no | `home:read` | 60 | — | allowlisted entities only |
| `web_search` | LOW | no | `web:read` | 20 | — | results flagged `untrusted` |
| `guest_greet` | LOW | no | `device:speak` | 10 | — | refuses anything that would identify a visitor |
| `set_alarm` | LOW | no | `device:alarm` | 20 | — | targets the caller's own linked device |
| `cancel_alarm` | LOW | no | `device:alarm` | 20 | — | same |
| `image_edit` | MEDIUM | yes | `media:write` | 20 | yes | background removal reports unavailable rather than faking it |
| `read_mail` | MEDIUM | yes | `mail:read` | 10 | — | IMAP opened read-only; never flags or deletes |
| `open_app` | MEDIUM | yes | `device:app_launch`, `owner_device` | 10 | — | fixed package allowlist |
| `pc_lock` | MEDIUM | yes | `device:desktop`, `owner_device` | 10 | — | desktop links only |
| `web_generate` | MEDIUM | yes | `web:build` | 10 | yes | writes to the sandbox; nothing is published |
| `web_preview` | MEDIUM | yes | `web:build` | 20 | — | signed, expiring preview URL |
| `messaging_reply` | **HIGH** (dynamic) | yes | `messaging:send` | 10 | yes | MEDIUM only for a pre-approved contact with auto-send; refuses unknown contacts |
| `web_deploy` | HIGH | yes | `web:deploy` | 3 | — | allowlisted destination + lint gate; the human sees repo and project |
| `call_answer` | HIGH | yes | `device:calls`, `owner_device` | 10 | — | owner's device only |
| `call_decline` | HIGH | yes | `device:calls`, `owner_device` | 10 | — | owner's device only |
| `call_place` | HIGH | yes | `device:calls`, `owner_device` | 5 | — | strict E.164 only |
| `link_device` | HIGH | yes | `device:link`, `owner_device` | 5 | — | VIP+; pairing only completes on the device |
| `unlink_device` | HIGH | yes | `device:link`, `owner_device` | 3 | — | needs a ticket minted after the device password check |
| `pc_unlock` | HIGH | yes | `device:desktop`, `owner_device` | 3 | — | needs a device-held proof; voice/face alone is never enough |

Legend: "Approval" means a single-use, hash-bound human approval is mandatory.
HIGH tools also require the `vip` or `admin` role when they carry `owner_device`.

## Explicitly out of scope (never implemented)

* Silent call or SMS interception, call recording, SMS reading.
* Hidden screen capture. Mirroring only runs as a visibly flagged session that
  either side can end instantly.
* Rotating across personal Anthropic accounts to evade plan limits. The platform
  only pools multiple keys belonging to the **same organisation**, billed to the
  owner's own account at standard usage-based pricing.
