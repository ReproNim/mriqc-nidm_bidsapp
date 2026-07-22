"""Regression checks for the documented BABS PR #369 configuration."""

from pathlib import Path


def test_bids_study_config_declares_new_babs_paths():
    root = Path(__file__).parents[1]
    config = (root / "examples" / "babs-mriqc-nidm-bids-study.yaml").read_text()
    dockerfile = (root / "Dockerfile").read_text()

    assert 'analysis_path: "."' in config
    assert 'input_ria_path: ".babs/input_ria"' in config
    assert 'output_ria_path: ".babs/output_ria"' in config
    assert '$SUBJECT_SELECTION_FLAG: "--participant-label"' in config
    assert '# $SESSION_SELECTION_FLAG: "--session-label"' in config
    assert 'mriqc-nidm_bidsapp: "0-1-0"' in config
    assert 'ENTRYPOINT ["mriqc-nidm"]' in dockerfile
