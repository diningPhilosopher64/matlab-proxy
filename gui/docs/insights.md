# Copyright 2026 The MathWorks, Inc.

# Development Insights

| Date | Skill | Worked Well | Unexpected | Do Differently |
|------|-------|-------------|------------|----------------|
| 2026-09-03 | tdd | Focused tests clearly distinguished expired device codes from other authorization errors. | Existing tests contain stale expectations for recently changed UI copy. | Keep UI-copy assertions synchronized with component copy changes. |
| 2026-09-03 | tdd | Testing expiry with changed message wording exposed coupling between presentation text and control flow. | The poll response already had an HTTP 410 semantic signal that was not propagated to the UI state. | Model error categories explicitly and keep display strings presentational. |
| 2026-09-03 | tdd | Waiting for the pending-state device code made the copy assertion deterministic. | Reusing identical text across consecutive views can make async queries capture a detached DOM node. | Await state-specific content before asserting text shared by multiple states. |
| 2026-09-03 | tdd | A DOM-level assertion verified that the spinner belongs to the intended pending-state message. | Applying the spinner class to the paragraph would style the whole message as the spinner. | Represent visual relationships with nested elements and test their containment. |
| 2026-09-03 | tdd | The pending-state test captured the exact requested copy and spinner relationship. | Similar waiting phrases made the intended replacement initially ambiguous. | Translate copy requests into explicit before-and-after assertions. |
