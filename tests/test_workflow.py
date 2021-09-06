from pathlib import Path
from typing import Generator, List, Tuple
import tempfile

from tests.fixtures import *

from insar.scripts.process_gamma import run_ard_inline
from insar.project import ARDWorkflow, ProcConfig, IfgFileNames
from insar.constant import SlcFilenames, MliFilenames
import insar.workflow.luigi.coregistration

test_data = Path(__file__).parent.absolute() / 'data'

def print_dir_tree(dir: Path, depth=0):
    print("  " * depth + dir.name + "/")

    depth += 1

    for i in dir.iterdir():
        if i.is_dir():
            print_dir_tree(i, depth)
        else:
            print("  " * depth + i.name)

def dir_tree(dir: Path) -> Generator[Path, None, None]:
    for i in dir.iterdir():
        yield i

        if i.is_dir():
            yield from dir_tree(i)

def count_dir_tree(dir: Path) -> int:
    if not dir.exists():
        return 0

    return len(list(dir_tree(dir)))

# Note: these tests run on fake source data products, so...
# 1) This doesn't test any of the DB query side of things
# 2) This, like all of our unit test, doesn't test the
#    correctness of any of the GAMMA data processing, only
#    the high level API checking that py_gamma_test_proxy.py does.


# TODO: in the future... we could detect if we're on the NCI and truly
# run these tests "without" the mock fixtures, and real data (not the
# tests/data/* stuff) and these should also run/pass.
#
# These tests are basically end-to-end workflow integration tests, and
# the ONLY two differences between this and a real processing job are
# the GAMMA mocks and fake testing data.
#
# These tests legitimately run the real-deal ARD luigi workflow directly,
# albeit slowly (single-threaded in the calling thread).


def do_ard_workflow_validation(
    pgp,
    workflow: ARDWorkflow,
    source_data: List[Path],
    pols: List[str],
    proc_file_path: Path,
    expected_errors: int = 0,
    min_gamma_calls: int = 10,
    validate_slc: bool = True,
    validate_ifg: bool = True,
    cleanup: bool = True,
    debug: bool = False
) -> Tuple[Path, Path, tempfile.TemporaryDirectory]:
    # Setup temporary dirs to run the workflow in
    temp_dir = tempfile.TemporaryDirectory()
    job_dir = Path(temp_dir.name) / "job"
    out_dir = Path(temp_dir.name) / "out"

    job_dir.mkdir()
    out_dir.mkdir()

    # Setup test workflow arguments
    args = {
        "proc_file": str(proc_file_path),
        "include_dates": '',
        "exclude_dates": '',
        "source_data": source_data,
        "workdir": str(job_dir),
        "outdir": str(out_dir),
        "polarization": pols,
        "cleanup": cleanup,
        "workflow": workflow
    }

    # Run the workflow
    run_ard_inline(args)

    # Load final .proc config
    finalised_proc_path = out_dir / "config.proc"
    with finalised_proc_path.open('r') as fileobj:
        proc_config = ProcConfig.from_file(fileobj)

    is_nrt = args["workflow"] == ARDWorkflow.BackscatterNRT
    is_coregistered = args["workflow"] != ARDWorkflow.BackscatterNRT
    rlks = int(proc_config.range_looks)

    # DEBUG for visualising output in tempdir
    print_out_dir = debug

    if print_out_dir:
        print("===== DEBUG =====")
        print_dir_tree(out_dir)
        print("==="*5)
    # END DEBUG

    print((job_dir / "status-log.jsonl").read_text())

    # Assert there were no GAMMA errors
    assert(pgp.error_count == expected_errors)

    # Assert we did call some GAMMA functions
    if min_gamma_calls == 0:
        assert(len(pgp.call_sequence) == 0)
    else:
        assert(len(pgp.call_sequence) >= min_gamma_calls)

    # Assert raw data was extracted from source data
    if not cleanup and source_data:
        raw_data_dir = out_dir / proc_config.raw_data_dir
        assert(raw_data_dir.exists())
        # There should be dozens of raw files in any source data
        assert(count_dir_tree(raw_data_dir) > 10)

    # Assert we have a csv of source data
    burst_data_csv = out_dir / f"{proc_config.stack_id}_burst_data.csv"
    assert(burst_data_csv.exists())

    # Assert our scene lists make sense
    ifgs_list = out_dir / proc_config.list_dir / "ifgs.list"
    if ifgs_list.exists():
        ifgs_list = ifgs_list.read_text().strip().splitlines()
    else:
        ifgs_list = []

    scenes_list = out_dir / proc_config.list_dir / "scenes.list"
    scenes_list = scenes_list.read_text().strip().splitlines()

    if scenes_list:
        primary_ref_scene = out_dir / proc_config.list_dir / "primary_ref_scene"
        primary_ref_scene = primary_ref_scene.read_text().strip()

        assert(primary_ref_scene == proc_config.ref_primary_scene)

    ifg_dir = out_dir / proc_config.int_dir

    if len(scenes_list) < 2 or workflow != ARDWorkflow.Interferogram:
        assert(len(ifgs_list) == 0)
    else:
        assert(len(ifgs_list) > 0)

    # Assert each scene has an SLC (coregistered if not NRT)
    #
    # TBD: It might be better to use the `required_files` variable in the
    # ARD luigi task?  as that is the expected pattern of files we expect
    # to exist (and are thus saved from being cleaned up).
    #
    # Might want to do this 'in addition' to this explicit code-based approach
    # as this current approach validates our SlcFilenames/etc constants are
    # being respected.  Where as the glob patterns are more of a higher level
    # encoding/representation of a business requirement.
    if validate_slc:
        for scene in scenes_list:
            scene_dir = out_dir / proc_config.slc_dir / scene
            assert(scene_dir.exists())

            for pol in pols:
                slc_file = scene_dir / SlcFilenames.SLC_FILENAME.value.format(scene, pol)
                slc_par_file = scene_dir / SlcFilenames.SLC_PAR_FILENAME.value.format(scene, pol)
                mli_file = scene_dir / MliFilenames.MLI_FILENAME.value.format(scene_date=scene, pol=pol, rlks=rlks)
                mli_par_file = scene_dir / MliFilenames.MLI_PAR_FILENAME.value.format(scene_date=scene, pol=pol, rlks=rlks)

                # If we haven't cleaned up, SLC data should exist
                if not cleanup:
                    assert(slc_file.exists())
                    assert(slc_par_file.exists())
                    assert(mli_file.exists())
                    assert(mli_par_file.exists())

                    def resampled(path: Path):
                        return path.parent / f"r{path.name}"

                    if is_coregistered and scene != primary_ref_scene:
                        assert(resampled(slc_file).exists())
                        assert(resampled(slc_par_file).exists())
                        assert(resampled(mli_file).exists())
                        assert(resampled(mli_par_file).exists())

                # Assert each scene has backscatter products
                if is_nrt:
                    gamma0_path = scene_dir / f"nrt_{scene}_{pol}_{rlks}rlks_gamma0_geo"
                    gamma0_tif_path = scene_dir / f"nrt_{scene}_{pol}_{rlks}rlks_gamma0_geo.tif"
                else:
                    gamma0_path = scene_dir / f"{scene}_{pol}_{rlks}rlks_geo.gamma0"
                    gamma0_tif_path = scene_dir / f"{scene}_{pol}_{rlks}rlks_geo.gamma0.tif"

                # Raw data only kept if not cleanup
                if not cleanup:
                    assert(gamma0_path.exists())

                # But we should always have a geotiff no matter what
                assert(gamma0_tif_path.exists())

    # Assert each IFG date pair has phase unwrapped geolocated data
    if validate_ifg:
        print_dir_tree(out_dir)
        if not ifgs_list:
            assert(not ifg_dir.exists() or len(list(ifg_dir.iterdir())) == 0)
        else:
            assert(len(list(ifg_dir.iterdir())) == len(ifgs_list))

        for date_pair in ifgs_list:
            primary_date, secondary_date = date_pair.split(",")

            ic = IfgFileNames(proc_config, primary_date, secondary_date, out_dir)

            # Make sure the main geo flat & unwrapped file exists
            assert((ic.ifg_dir / ic.ifg_unw_geocode_out_tiff).exists())
            assert((ic.ifg_dir / ic.ifg_flat_geocode_out_tiff).exists())
            assert((ic.ifg_dir / ic.ifg_flat).exists())

            # Ensure filt/flat products exist
            assert((ic.ifg_dir / ic.ifg_filt_geocode_out_tiff).exists())
            assert((ic.ifg_dir / ic.ifg_filt_coh_geocode_out_tiff).exists())
            assert((ic.ifg_dir / ic.ifg_flat_geocode_out_tiff).exists())
            assert((ic.ifg_dir / ic.ifg_flat_coh_geocode_out_tiff).exists())

    return out_dir, job_dir, temp_dir

def test_ard_workflow_ifg_single_s1_scene(pgp, pgmock, s1_proc, s1_test_data_zips):
    # Take just first 2 source data files (which is a single date, each date has 2 acquisitions in a frame)
    source_data = [str(i) for i in s1_test_data_zips[:2]]
    pols = ["VV", "VH"]

    with s1_proc.open('r') as fileobj:
        proc_config = ProcConfig.from_file(fileobj)

    # Create empty orbit files
    for name in ["s1_orbits", "poeorb_path", "resorb_path", "s1_path"]:
        (Path(getattr(proc_config, name)) / "S1A").mkdir(parents=True)

    poeorb = Path(proc_config.poeorb_path) / "S1A" / "S1A_OPER_AUX_POEORB_OPOD_20190918T120745_V20190917T225942_20190919T005942.EOF"
    poeorb.touch()

    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        s1_proc
    )


def test_ard_workflow_ifg_smoketest_two_date_s1_stack(pgp, pgmock, s1_proc, s1_test_data_zips):
    source_data = [str(i) for i in s1_test_data_zips]
    pols = ["VV", "VH"]

    with s1_proc.open('r') as fileobj:
        proc_config = ProcConfig.from_file(fileobj)

    # Create empty orbit files
    for name in ["s1_orbits", "poeorb_path", "resorb_path", "s1_path"]:
        (Path(getattr(proc_config, name)) / "S1A").mkdir(parents=True, exist_ok=True)

    for date in S1_TEST_DATA_DATES:
        poeorb = Path(proc_config.poeorb_path) / "S1A" / "S1A_OPER_AUX_POEORB_OPOD_20190918T120745_V20190917T225942_20190919T005942.EOF"
        poeorb.touch()

    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        s1_proc
    )


def test_ard_workflow_ifg_smoketest_single_rs2_scene(pgp, pgmock, rs2_test_data, rs2_proc):
    # Setup test workflow arguments, taking just a single RS2 acquisition
    source_data = [str(rs2_test_data[0])]
    pols = ["HH"]

    # Run standard ifg workflow validation test for this data
    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        rs2_proc
    )

def test_ard_workflow_ifg_smoketest_two_date_rs2_stack(pgp, pgmock, rs2_test_data, rs2_proc):
    # Setup test workflow arguments
    source_data = [str(i) for i in rs2_test_data]
    pols = ["HH"]

    # Run standard ifg workflow validation test for this data
    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        rs2_proc
    )


#
# Note: The tests below don't differ inside of the workflow between sensors,
# as such to avoid duplicating tests for no reason we just have one version
# of each based on RS2 data.  This 'might' change in the future, at which
# point test coverage may drop (and this may need to be revised).
#

def test_ard_workflow_smoketest_nrt(pgp, pgmock, rs2_test_data, rs2_proc):
    # Setup test workflow arguments
    source_data = [str(i) for i in rs2_test_data]
    pols = ["HH"]

    # Run standard ifg workflow validation test for this data
    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.BackscatterNRT,
        source_data,
        pols,
        rs2_proc
    )


def test_ard_workflow_pol_mismatch_produces_no_data(pgp, pgmock, rs2_test_data, rs2_proc):
    # Setup test workflow arguments
    source_data = [str(i) for i in rs2_test_data]
    # But with a mismatching pols! (rs2 test data is HH, not VV)
    pols = ["VV"]

    # Run standard ifg workflow validation test for this data
    # expected calls == 0!
    out_dir, _, _ = do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        rs2_proc,
        min_gamma_calls=0,
        debug=True
    )

    assert(not (out_dir / 'lists' / 'scenes.list').read_text().strip())


def test_ard_workflow_excepts_on_dag_errors(monkeypatch, pgp, pgmock, rs2_test_data, rs2_proc):
    # We inject an error in this test, to the get_scenes function - which most
    # non-processing tasks (eg: the Create* tasks which create processing tasks)
    # use to determine what the input scenes are... so this will cause errors pretty
    # early on in a Luigi task (eg: CreateCoregisterSecondaries)
    test_message = "No backscatter for you! >:|"

    def get_exception(*args, **kwargs):
        raise Exception(test_message)

    monkeypatch.setattr(insar.workflow.luigi.coregistration, "get_scenes", get_exception)

    # Setup test workflow arguments
    source_data = [str(i) for i in rs2_test_data]
    pols = ["HH"]

    # Run standard ifg workflow validation test, which should raise our exception!
    # - as the tasks that get it will 'not' be processing tasks, but other tasks
    # - in the DAG which should NOT be allowed to fail / can not soldier on.
    with pytest.raises(Exception) as ex_info:
        _, job_dir, _ = do_ard_workflow_validation(
            pgp,
            ARDWorkflow.Backscatter,
            source_data,
            pols,
            rs2_proc,
            # Don't validate outputs, as they won't exist from our error
            validate_slc=False
        )

        assert(ex_info.value.message == test_message)


def test_ard_workflow_processing_errors_do_not_except(pgp, pgmock, rs2_test_data, rs2_proc):
    # We inject a processing error into the backscatter code which should not cause any
    # exception, as it should not flow out of the workflow (they should be captured and
    # the workflow should soldier on when raised within a processing module).
    #
    # float_math is only done for gamma0 calcs, this was chosen to cause backscatter
    # to fail in this unit test.
    def raise_error(*args, **kwargs):
        raise Exception("Test error!")

    pgmock.float_math.side_effect = raise_error

    # Setup test workflow arguments
    source_data = [str(rs2_test_data[0])]
    pols = ["HH"]

    # Run standard ifg workflow validation test, it should NOT except in this case
    # despite us raising an exception above.  As the tasks that get the error are
    # data processing tasks which should be allowed to fail / soldier on.
    _, job_dir, _ = do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Backscatter,
        source_data,
        pols,
        rs2_proc,
        # Don't validate outputs, as they won't exist from our error
        validate_slc=False,
        validate_ifg=False
    )

    # Assert our exception was thrown (despite it not making it outside of luigi)
    assert(pgmock.float_math.call_count > 0)

    # Assert the DAG output file has a failed status
    nbr_status_text = (job_dir / "tasks" / "20170430_HH_2rlks_nbr_logs.out").read_text()
    assert(nbr_status_text == "FAILED")


def test_ard_workflow_excepts_on_invalid_proc(pgp, pgmock, rs2_test_data, rs2_proc):
    # Setup test workflow arguments
    source_data = [str(i) for i in rs2_test_data]
    pols = ["HH"]

    # Create invalid .proc file
    proc_txt = rs2_proc.read_text()[2000:]

    bad_proc = rs2_proc.parent / "invalid_rs2_proc.config"
    with bad_proc.open("w") as file:
        file.write(proc_txt)

    # Run standard ifg workflow validation test, which should except
    with pytest.raises(Exception):
        do_ard_workflow_validation(
            pgp,
            ARDWorkflow.Interferogram,
            source_data,
            pols,
            bad_proc,
            min_gamma_calls=0
        )

    # Assert no GAMMA calls were ever made
    assert(len(pgp.call_sequence) == 0)


def test_ard_workflow_no_op_for_empty_data(pgp, pgmock, rs2_proc):
    # Setup test workflow arguments
    source_data = []
    pols = ["VV"]

    # Run standard ifg workflow validation test for this data
    # - shouldn't except
    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        rs2_proc,
        # Except no GAMMA calls w/ no data inputs
        min_gamma_calls=0
    )


def test_ard_workflow_no_cleanup_keeps_raw_data(pgp, pgmock, rs2_test_data, rs2_proc):
    # Setup test workflow arguments
    source_data = [str(i) for i in rs2_test_data]
    pols = ["HH"]

    # Run standard ifg workflow validation test for this data
    do_ard_workflow_validation(
        pgp,
        ARDWorkflow.Interferogram,
        source_data,
        pols,
        rs2_proc,
        cleanup=False
    )

    # Note: do_ard_workflow_validation does all the validation we care about when cleanup == False
    # - no need to duplicate it here.
