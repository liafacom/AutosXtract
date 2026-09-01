# Pinned by tag, not by `latest`: a container that reproduces a different
# environment every time it is rebuilt is not reproducing anything. 3.13 is what
# .python-version says the project develops on, and what constraints/dev.txt was
# resolved against.
FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

# The only things pip cannot bring, and each one is here for a reason a comment
# has to carry, because the failure it prevents is silent:
#
#   libgl1, libglib2.0-0  — `opencv-python` (pulled in by rapidocr) links
#       against libGL. Slim images have no X stack, `import cv2` then raises
#       ImportError, the OCR step goes inert and the cascade quietly shortens to
#       `native`: a scanned PDF comes out EMPTY and nothing looks broken.
#       scripts/bootstrap.sh also reasserts the headless build for the same
#       reason — two defences, because this one has no symptom.
#   tesseract-ocr(-por)   — the veto witness is a BINARY. pytesseract installs
#       without it and fails on the first page. Portuguese because that is the
#       corpus the patterns describe. Installed here but NOT enabled by default;
#       see postCreateCommand in devcontainer.json.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        tesseract-ocr \
        tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*
