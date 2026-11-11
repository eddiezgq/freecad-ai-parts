# FAQ

> Look here first when something goes wrong.

## Shop floor

- **Clicked start, but the part does not move**: the previous operation has not delivered the part yet, or nobody started the previous operation.
- **No “Start” button on the shop terminal**: nothing is dispatched to this machine yet; release the work order in “Orders & planning” first.
- **The machine stays 🔒 and “Reset” does nothing**: the shop rejects resets during lockout. Find this machine's order in “Maintenance” or “Safety & environment”, finish it, and have someone else “verify and unlock”.
- **The machine shows 👤 “Nobody can run it this shift”**: find the red cell under “People → Roster” and change people, or open “Staffing gap” in the command center for options.
- **A yellow notice at the top of the shop terminal**: for “Cannot reach the unified data bus” click “Retry”, and tell the teacher if it persists; for “Production mode shows only connected real machines” click “Switch to teaching mode”.
- **Home page numbers do not move**: check whether the “unified data bus” at the bottom of the left sidebar is connected; at 1× speed changes are slow, which is normal.

## Plant Insight Hub and labs

- **No “Suggestion” in the right panel**: you are in compare mode. Submit your own choice on the lab page first; it shows after that.
- **Cannot click “Adopt, create actions”**: this action must be started by a specific role (e.g. PM by maintenance, dispatch by customer service). Change roles at the top right; or the option “failed checks”.
- **An action stays “Awaiting approval”**: actions that cost money need the plant manager; ask the teacher to approve; you cannot approve your own.
- **An anomaly never appears**: rules check every 20 seconds; some need the shop to run a while for data (e.g. a meter reading every 15 factory minutes).
- **No labs under “Labs & tasks”**: labs appear only in teaching mode; switch to “Teaching mode” at the top right.

## Design and process

- **“Release new revision” in online design is gray**: the checks failed; read the red text (e.g. the keyway is longer than its shaft segment); yellow text is a hint that differs from the national standard recommendation — click “Use recommended” or release without changing.
- **Desktop CAD release says “Please sign in first”**: the credentials in the macro package are valid for 7 days; download the macro package again from the “Design & process” page.

## Proposals and ERPNext

- **A proposal keeps showing “In progress”**: ask the teacher to check the bridge log.
- **Document, asset or employee numbers are empty for now**: after writing to ERPNext, the bridge takes from a few seconds to a minute or two to read them back. Wait and refresh.
- **Cannot place orders in ERPNext**: students can only view in ERPNext; place orders, run MRP and start work on the workbench.

## Time

- **Factory time differs from real time**: the shop runs at a speed multiple; “minutes” and “hours” on pages are factory time by default.
- **Billing days**: supplier deliveries, invoices and payments count in billing days; in teaching mode 1 day = 2 real minutes.
- **Script days**: in the two-week scenario “day N” is only a label.

```ask
q: I clicked start but the part does not move. What do I do?
```
