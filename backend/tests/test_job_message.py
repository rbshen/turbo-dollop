from helpers.job_message import counted, labelled, name_list


def test_name_list_caps_at_ten_then_counts_the_rest():
    assert name_list([]) == ""
    assert name_list(["A", "B"]) == "A, B"
    assert name_list([f"T{i}" for i in range(10)]).endswith("T9")
    assert name_list([f"T{i}" for i in range(12)]) == ", ".join(f"T{i}" for i in range(10)) + ", +2 more"


def test_counted_and_labelled_add_names_only_when_given():
    assert counted(1, "failed", ["BF-B"]) == "1 failed (BF-B)" and counted(0, "failed", []) == "0 failed" and counted(3, "failed") == "3 failed"
    assert labelled("failed", 1, ["BBB"]) == "failed 1 (BBB)" and labelled("gaps", 3) == "gaps 3"
