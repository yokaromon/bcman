from evaluate_orientation_consistency import relative_corrections_are_consistent


def test_relative_four_rotation_consistency():
    results = [
        {"status": "auto_confirmed", "rotation_applied": value}
        for value in (0, 270, 180, 90)
    ]
    assert relative_corrections_are_consistent(results)
    results[2]["rotation_applied"] = 0
    assert not relative_corrections_are_consistent(results)


def test_uncertain_variant_is_not_counted_as_consistent():
    results = [
        {"status": "auto_confirmed", "rotation_applied": value}
        for value in (90, 0, 270, 180)
    ]
    results[3]["status"] = "uncertain"
    assert not relative_corrections_are_consistent(results)
