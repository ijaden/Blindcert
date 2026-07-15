from blindcert.models.logistic_regression import LogisticRegressionModel
from blindcert.types import QuantizationSpec


def test_logistic_regression_predicts_binary_label() -> None:
    model = LogisticRegressionModel(QuantizationSpec(0, 8, 32), {"weights": [1, -1], "bias": 0})
    assert model.predict_one([3, 1]) == 1
    assert model.predict_one([1, 3]) == 0
