from blindcert.benchmark.system_models import IntegerModel, generate_model


def test_quadratic_activation_retains_negative_hidden_preactivation() -> None:
    model = IntegerModel('quadratic', 'quadratic_mlp', (1, 1, 1), (1, 0, 1, -1))
    assert model.predict([-1]) == 1


def test_polynomial_svm_uses_each_cross_term_once() -> None:
    model = IntegerModel('svm', 'polynomial_svm', (2, 1), (-1, 0, 0, 0, 1, 0))
    assert model.predict([1, 1]) == 1
    assert model.predict([1, -1]) == 0


def test_large_model_parameter_count_and_exact_integer_bounds() -> None:
    spec = {'name': 'MLP-D256-H128,64', 'kind': 'quadratic_mlp', 'layers': [256, 128, 64, 1]}
    model = generate_model(spec, 20261105)
    assert len(model.parameters) == 41217
    assert model == generate_model(spec, 20261105)
    bound = 1
    for layer, item in enumerate(model.bounds()):
        linear = model.layers[layer] * bound + 1
        assert item['preactivation_absolute_bound'] == linear
        bound = linear ** 2 if layer < len(model.layers) - 2 else linear
        assert item['absolute_bound'] == bound
    assert model.bounds()[-1]['signed_bits'] < 254
