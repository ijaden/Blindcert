from blindcert.benchmark.system_models import generate_model
from blindcert.benchmark.system_relation import arithmetic, policy, poseidon
from blindcert.benchmark.system_runtime import selected


def test_poseidon_reference_matches_published_two_input_vector() -> None:
    assert poseidon([1, 2]) == 7853200120776062878684798364095072458815029376092732009249414926327459813530


def test_stratified_challenge_is_reproducible_without_duplicates() -> None:
    config = {'population_size':1024,'sample_size':128}
    result = selected('01'*32,config)
    assert result == selected('01'*32,config)
    assert len(result) == len(set(result)) == 128
    assert sum(index < 512 for index in result) == 64
    assert all(0 <= index < 1024 for index in result)


def test_formal_policy_is_feasible_and_uses_population_weights() -> None:
    result = policy({'sample_size':128})
    assert result['required_correct_per_stratum'] == 60
    assert result['allowed_violations_per_stratum'] == 4
    assert result['population_weights'] == [0.5,0.5]


def test_generated_arithmetic_matches_independent_integer_reference() -> None:
    for kind,layers in [('linear',[2,1]),('quadratic_mlp',[2,3,2,1]),('polynomial_svm',[2,1])]:
        spec = {'name':kind,'kind':kind,'layers':layers}
        model = generate_model(spec,20261105)
        records = [[-1,1],[0,0],[1,-1]]
        source,scores = arithmetic(spec,3,'mpc')
        namespace = {'theta':list(model.parameters),'x':sum(records,[])}
        exec('\n'.join(source),namespace)
        assert [int(namespace[name]>=0) for name in scores] == [model.predict(x) for x in records]
