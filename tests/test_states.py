from core.reference.states import _PIN3_RANGES, STATES, state_from_pincode


def test_state_from_pincode() -> None:
    assert state_from_pincode("442104") == "Maharashtra"  # Seldoh (from the CPPP fixture)
    assert state_from_pincode("110001") == "Delhi"
    assert state_from_pincode("403001") == "Goa"
    assert state_from_pincode("500001") == "Telangana"
    assert state_from_pincode("834001") == "Jharkhand"  # Ranchi
    assert state_from_pincode("800001") == "Bihar"  # Patna
    assert state_from_pincode("248001") == "Uttarakhand"  # Dehradun
    assert state_from_pincode("NA") is None
    assert state_from_pincode(None) is None


def test_every_mapped_state_is_a_known_state() -> None:
    assert {s for *_, s in _PIN3_RANGES} <= set(STATES)
