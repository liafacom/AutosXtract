# 0.5.0 — the contract and the patterns became public API.
#
# MINOR: two subsystems that shipped inside 0.4.0's tree without a version
# number of their own, and one veto path that had no test.
#
#   * ``interfaces.py`` — eleven structural ``Protocol``s, each with a
#     conformance test. It imports nothing at runtime, which is what keeps it
#     below all five layers of CLAUDE.md §10. A collaboration written down only
#     in a docstring drifts: ``Engine`` published ``transcribe(pages, *,
#     parallelism)`` while ``OCRStep`` passed ``force_parallelism`` for months.
#   * ``patterns/`` — the Portuguese regexes as a TOML pack rather than
#     ``re.compile`` in ten files. A user pack overrides entry by entry, so a
#     pack that redefines one stamp keeps receiving fixes to the other
#     sixty-five. File-level merging would force a copy, and a copy is a fork.
#   * ``InkSignals`` — ``quality/vetoes.py`` called ``pdf.ink`` directly, which
#     put I/O in ``quality/`` and left the two pixel vetoes untestable (87%
#     coverage, the gap exactly on lines 97-100). Those are the two §13 warns
#     are valid ONLY with "extracted no text" — alone they discard an old
#     photocopy on dark paper. Injected now; behaviour unchanged, 98%.
__version__ = "0.5.0"
