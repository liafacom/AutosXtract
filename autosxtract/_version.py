# 0.4.0 — the engines themselves became configurable.
#
# MINOR: the registry's ``get`` gained options, and ``Config`` a field.
#
#   * ``get(name, **options)`` passes constructor arguments through. Engines
#     were built by ``factory()`` with NO arguments, so PP-OCR's tier, the INT8
#     flag, the ONNX thread count, the preprocessing and the execution
#     providers were unreachable from an assembled cascade. A knob that exists
#     in the constructor and cannot be turned from outside is not a knob.
#     Instances are cached by ``(name, options)``: asking for INT8 must not
#     hand back the FP32 model somebody built first.
#   * ``Config.engine_options`` — the same, for whoever configures rather than
#     constructs.
#   * ``quantized`` stopped lying. It was read only by the paddleocr backend;
#     with rapidocr — the backend most installs get — it was accepted, reported
#     as INT8, and FP32 ran. Now it uses ``int8/`` weights when they are on
#     disk and SAYS SO when they are not.
__version__ = "0.4.0"
