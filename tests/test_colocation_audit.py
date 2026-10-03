from evals import colocation_audit as A

HEADER = "JobID|JobName|NodeList|Start|End|State|ExitCode"


def sacct(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def test_job_names_map_to_the_model_they_serve():
    m = A.model_of
    assert (
        m("ledgerql-eval-30b") == m("ledgerql-gen-30b") == m("ledgerql-gen-30b-link") == "qwen3_30b"
    )
    assert m("ledgerql-eval-32b") == m("ledgerql-gen-32b-awq") == "qwen25_32b_awq"
    assert m("ledgerql-gen-xiyan-32b") == m("ledgerql-gen-xiyan-link") == "xiyan_32b"
    assert m("ledgerql-gen-omnisql-32b") == "omnisql_32b"
    assert m("something-else") == "unknown"


def test_two_jobs_serving_the_same_model_on_one_node_at_once_are_the_silent_case():
    text = sacct(
        "47314848|ledgerql-gen-30b-link|w006|2026-10-01T12:34:36|2026-10-01T12:41:34|COMPLETED|0:0",
        "47314853|ledgerql-eval-30b|w006|2026-10-01T12:38:00|2026-10-01T12:41:34|COMPLETED|0:0",
        "47314850|ledgerql-gen-xiyan-link|w006|2026-10-01T12:34:36|2026-10-01T12:37:41|FAILED|3:0",
    )
    out = A.audit(A.parse_sacct(text))
    assert [(p["a"], p["b"]) for p in out["same_model"]] == [("47314848", "47314853")]
    assert out["same_model"][0]["node"] == "w006" and out["same_model"][0]["overlap_seconds"] == 214
    # the cross-model pairs are loud: reported with whether either job failed
    loud = {(p["a"], p["b"]): p["a_or_b_failed"] for p in out["cross_model"]}
    # XiYan ended 12:37:41, before the pipeline job started at 12:38:00: one pair overlaps
    assert loud == {("47314848", "47314850"): True}


def test_same_model_on_different_nodes_or_at_different_times_is_not_flagged():
    text = sacct(
        "1|ledgerql-eval-30b|w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0",
        # another node:
        "2|ledgerql-gen-30b|w002|2026-09-20T10:05:00|2026-09-20T10:25:00|COMPLETED|0:0",
        # starts the instant job 1 ends:
        "3|ledgerql-gen-30b|w001|2026-09-20T10:30:00|2026-09-20T11:00:00|COMPLETED|0:0",
    )
    out = A.audit(A.parse_sacct(text))
    assert out["same_model"] == [] and out["cross_model"] == []


def test_a_job_with_no_start_or_no_node_is_listed_as_unaudited_not_silently_skipped():
    text = sacct(
        "1|ledgerql-eval-30b|w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0",
        "2|ledgerql-gen-30b|None assigned|Unknown|Unknown|CANCELLED|0:0",
        "3|unrelated-job|w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0",
    )
    out = A.audit(A.parse_sacct(text))
    assert [j["id"] for j in out["unaudited"]] == ["2"]
    assert (
        out["jobs"] == 2
    )  # the unrelated job is ignored, the cancelled one is counted as unaudited


def test_job_steps_are_collapsed_into_their_job():
    text = sacct(
        "9|ledgerql-eval-30b|w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0",
        "9.batch||w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0",
        "9.extern||w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0",
    )
    assert A.audit(A.parse_sacct(text))["jobs"] == 1


def test_the_report_names_the_command_to_run_and_states_a_clean_result_plainly():
    clean = A.render(
        A.audit(
            A.parse_sacct(
                sacct(
                    "1|ledgerql-eval-30b|w001|2026-09-20T10:00:00|2026-09-20T10:30:00|COMPLETED|0:0"
                )
            )
        )
    )
    assert "No two jobs serving the same model overlapped on one node" in clean
    assert "sacct" in A.SACCT_COMMAND and "NodeList" in A.SACCT_COMMAND
