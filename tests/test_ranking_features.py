from src.brain.ranking_features import extract_query_features, score_path_features, noise_penalty


def test_extracts_dotted_module_and_path_features():
    f = extract_query_features(
        "Bug in astropy.modeling.separable",
        "Failure in astropy/modeling/tests/test_separable.py with TypeError",
    )
    assert "astropy.modeling.separable" in f.dotted_modules
    assert "astropy/modeling/tests/test_separable.py" in f.file_paths
    assert "astropy/modeling/separable.py" in f.test_source_candidates
    assert f.weighted_terms["separable"] > 1.0


def test_scores_module_path_match():
    f = extract_query_features("Bug in astropy.modeling.separable")
    score, reasons = score_path_features("astropy/modeling/separable.py", f)
    assert score >= 12.0
    assert any("module" in r for r in reasons)


def test_scores_test_to_source_mapping():
    f = extract_query_features("", "Failure in package/tests/test_parser.py")
    score, reasons = score_path_features("package/parser.py", f)
    assert score >= 9.0
    assert any("test-to-source" in r for r in reasons)


def test_noise_penalty_is_soft_for_generic_files_without_strong_signal():
    factor, reasons = noise_penalty("src/utils.py", matches={"identifier": ["auth"]})
    assert 0 < factor < 1
    assert reasons


def test_noise_penalty_keeps_generic_file_with_direct_signal():
    factor, reasons = noise_penalty("src/utils.py", matches={"filename": ["utils"]})
    assert factor == 1.0
    assert reasons == []
