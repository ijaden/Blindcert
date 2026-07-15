import pytest

from blindcert.quantization import QuantizationError, encode_scalar
from blindcert.types import QuantizationSpec


def test_quantization_rounding_and_overflow() -> None:
    qspec = QuantizationSpec(scale_bits=2, value_bits=4, accumulator_bits=16)
    assert encode_scalar(1.25, qspec) == 5
    with pytest.raises(QuantizationError):
        encode_scalar(9.0, qspec)
