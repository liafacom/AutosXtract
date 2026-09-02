# 0.6.0 — a review pass, and the orientation fix stops being invisible.
#
# MINOR, and by this project's own reading of semver rather than by signatures:
# a changed default changes what the library accepts, and a caller's output
# changes underneath them. Two entries here do exactly that.
#
#   * ``Config.fix_orientation`` defaults to True. The correction already
#     existed and already sat before any engine saw a pixel; being off meant a
#     sideways page went to OCR sideways and every gate downstream judged an
#     input defect it cannot see. Its cost is one OSD pass per rasterised page
#     and it is UNMEASURED on this project's archive — the field says so.
#   * ``DocumentContext`` gained ``orientation``. A context implemented outside
#     the library now needs the attribute to satisfy ``isinstance``. The
#     twenty-line fake in the conformance test grew one line, which is the whole
#     migration.
#
# The rest is the review pass: per-page routing no longer drops the native half
# of a mixed PDF, ``Config.min_score`` reaches the acceptance gate, ``NativeStep``
# decides with ``quality.gate.evaluate`` like every other step, and a correction
# or a witness that could not run now says so instead of leaving evidence
# identical to one that ran.
__version__ = "0.6.0"
