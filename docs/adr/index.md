# Decision records

Eleven decisions that are **not** obvious from the code and that have already
cost something once. Each one is short, and each one carries the measurement that
settled it — because a decision without its evidence is an opinion, and an
opinion is something the next person reasonably overrules.

They exist for one reason: **the argument is more expensive than the code.** Any
of these can be undone in an afternoon. Reconstructing why it was made takes an
archive, a reviewer and a week, and in several cases here it took a silent
production failure first.

Every record follows the same template:

**Context** — what was true when the question came up.
**Decision** — what was decided, in one sentence.
**Consequences** — what you now have to live with, including the parts that are
inconvenient.
**Evidence** — the measurement. If a record has none, it is not a decision, it is
a preference, and it does not belong here.

| # | decision | status |
|---|---|---|
| [0001](0001-no-networking-in-the-default-cascade.md) | The default cascade does no networking, and networking is never accidental | accepted |
| [0002](0002-one-acceptance-criterion.md) | There is one acceptance criterion | accepted |
| [0003](0003-a-missing-engine-is-never-an-exception.md) | A missing engine is never an exception | accepted |
| [0004](0004-refused-text-still-competes.md) | Refused text still competes | accepted |
| [0005](0005-the-replacement-gate-discards.md) | The replacement gate discards what it refuses | accepted |
| [0006](0006-pymupdf-is-serialised.md) | PyMuPDF is serialised by a process lock | accepted |
| [0007](0007-confidence-does-not-arbitrate-quality.md) | Engine confidence does not arbitrate quality | accepted |
| [0008](0008-patterns-are-data.md) | The domain patterns are data, not Python | accepted |
| [0009](0009-interfaces-are-the-extension-seam.md) | Interfaces are the extension seam | accepted |
| [0010](0010-parallelism-is-decided-by-the-machine.md) | Parallelism is decided by the machine, not by the code | accepted |
| [0011](0011-no-real-document-in-the-repository.md) | No real document in the repository | accepted |

## Writing a new one

Number it sequentially, add it to the table above **and to the `nav` in
`mkdocs.yml`** — the site is built with `--strict`, so a page in no nav entry
fails the build rather than hiding.

If you cannot fill in **Evidence**, do not write the record. Write the
measurement first.

If you are **overturning** one, do not delete it. Add a new record that
supersedes it and say so in both, with the measurement that changed. The value of
this directory is that it holds the arguments that were already had, including
the ones that turned out to be wrong.
