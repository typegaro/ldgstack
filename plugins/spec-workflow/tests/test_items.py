"""0.13.0: `L<n>` (defined later) and `A<n>` (accepted risk) items in spec bodies, resolved by a newer spec's `Resolves` line."""
from __future__ import annotations

import unittest

from test_parallel import ScheduleCase
from test_workflow import spec_text

PARENT = """# Parent

- **R1** Behavior.

## Defined later

- **L1** Streaming to the browser: how replies stream, and what happens when the tab closes.
- **L2** Keep-warm policy

## Accepted risks

- **A1** Single database: an outage stops every tenant. Revisit at the first paying tenant.

```markdown
- **L9** Inside a fence: not an item.
```
"""


class ItemsTest(ScheduleCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_spec("0001-parent.md", spec_text(1, "parent", body=PARENT))

    def refs(self, command: str, *flags: str) -> list[str]:
        return [item["ref"] for item in self.spec(command, *flags)["result"]]

    def test_items_are_listed_with_title_detail_and_line(self) -> None:
        later = self.spec("later")["result"]
        self.assertEqual([item["ref"] for item in later], ["1:L1", "1:L2"])
        self.assertEqual((later[0]["title"], later[0]["status"], later[0]["spec_status"]), ("Streaming to the browser", "open", "draft"))
        self.assertTrue(later[0]["detail"].startswith("how replies stream"))
        self.assertEqual((later[1]["title"], later[1]["detail"]), ("Keep-warm policy", ""))
        lines = (self.root / "specs" / "0001-parent.md").read_text(encoding="utf-8").split("\n")
        self.assertTrue(lines[later[0]["line"] - 1].startswith("- **L1**"))
        self.assertEqual(self.refs("risks"), ["1:A1"])
        self.assertIn("0001:L1 Streaming to the browser: how replies", self.text("later"))
        self.assertEqual(self.spec("status")["result"]["open_items"], {"later": 2, "risk": 1})

    def test_resolves_closes_items(self) -> None:
        self.write_spec("0002-streaming.md", spec_text(2, "streaming", body="# Streaming\n\nResolves 1:L1 and 1:A1.\n\n- **R1** Stream.\n"))
        self.assertEqual(self.refs("later"), ["1:L2"])
        self.assertEqual(self.refs("risks"), [])
        everything = {item["ref"]: item for item in self.spec("later", "--all")["result"]}
        self.assertEqual(everything["1:L1"]["status"], "resolved")
        self.assertEqual([entry["id"] for entry in everything["1:L1"]["resolved_by"]], [2])
        self.assertIn("-> resolved by 0002", self.text("later", "--all"))
        self.assertTrue(self.spec("validate")["result"]["valid"])

    def test_superseded_spec_items_leave_the_default_list(self) -> None:
        self.write_spec("0002-new-parent.md", spec_text(2, "new-parent", supersedes=[1]))
        self.assertEqual(len(self.refs("later")), 2)  # superseded only once the superseding spec is accepted
        self.accept("0002-new-parent.md")
        self.assertEqual(self.refs("later"), [])
        self.assertEqual(len(self.refs("later", "--all")), 2)

    def test_validate_rejects_bad_links_and_duplicates(self) -> None:
        self.write_spec("0002-bad.md", spec_text(2, "bad", body="# Bad\n\nResolves 1:L7, 3:L1.\n\n- **R1** x.\n- **L1** a\n- **L1** b\n"))
        self.write_spec("0003-later.md", spec_text(3, "later", body="# Later\n\n- **L1** c\n"))
        message = self.spec("validate", succeeds=False)["error"]["message"]
        self.assertIn("Resolves 1:L7, but 0001 has no item L7", message)
        self.assertIn("Resolves 3:L1 must point to a lower spec id", message)
        self.assertIn("0002-bad.md: duplicate item L1", message)


if __name__ == "__main__":
    unittest.main()
