import io
import pathlib
import functools
import subprocess
from unittest import mock

import insar.constant as const
from insar import process_ifg, py_gamma_ga
from insar.process_ifg import ProcessIfgException
from insar.project import ProcConfig, IfgFileNames, DEMFileNames

import structlog
import pytest


# FIXME: tweak settings to ensure working dir doesn't have to be changed for INT processing (do in workflow)
# FIXME: change all mocks to return (return_code, cout, cerr) as per decorator

# TODO: can monkeypatch be done at higher level scope to apply to multiple test funcs?
@pytest.fixture
def pg_int_mock():
    """Create basic mock of the py_gamma module for INT processing step."""
    pg_mock = mock.Mock()
    pg_mock.create_offset.return_value = 0
    pg_mock.offset_pwr.return_value = 0
    pg_mock.offset_fit.return_value = 0
    pg_mock.create_diff_par.return_value = 0
    return pg_mock


@pytest.fixture
def pc_mock():
    """Returns basic mock to simulate a ProcConfig object."""
    pc = mock.Mock(spec=ProcConfig)
    pc.multi_look = 2  # always 2 for Sentinel 1
    pc.ifg_coherence_threshold = 2.5  # fake value
    return pc


@pytest.fixture
def ic_mock():
    """Returns basic mock to simulate an IfgFileNames object."""
    ic = mock.Mock(spec=IfgFileNames)

    mock_path = functools.partial(mock.MagicMock, spec=pathlib.Path)
    ic.ifg_bperp = mock_path()
    ic.r_master_slc = mock_path()
    ic.r_master_mli = mock_path()
    ic.r_slave_slc = mock_path()
    ic.r_slave_mli = mock_path()
    return ic


@pytest.fixture
def remove_mock():
    """Returns basic mock to simulate remove_files()."""
    rm = mock.Mock()
    return rm


@pytest.fixture
def subprocess_mock():
    """
    Subprocess module replacement.

    Can be too broad as it prevents access to subprocess exceptions.
    """
    m_subprocess = mock.Mock(spec=subprocess)
    m_subprocess.PIPE = "Fake pipe"
    return m_subprocess


def test_run_workflow_full(
    monkeypatch, pc_mock, ic_mock, dc_mock, remove_mock, subprocess_mock
):
    """Test workflow runs from end to end"""

    # mock out larger elements like modules/dependencies
    m_pathlib = mock.MagicMock()
    monkeypatch.setattr(process_ifg, "pathlib", m_pathlib)

    m_pygamma = mock.MagicMock()
    m_pygamma.base_perp.return_value = "fake-stat", "fake-cout", "fake-cerr"
    monkeypatch.setattr(process_ifg, "pg", m_pygamma)
    monkeypatch.setattr(process_ifg, "subprocess", subprocess_mock)

    # mock out smaller helper functions (prevent I/O etc)
    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    fake_width10 = 334
    fake_width_in = 77
    fake_width_out = 66
    monkeypatch.setattr(process_ifg, "get_width10", lambda _: fake_width10)
    monkeypatch.setattr(process_ifg, "get_width_in", lambda _: fake_width_in)
    monkeypatch.setattr(process_ifg, "get_width_out", lambda _: fake_width_out)

    # mock required individual values
    pc_mock.ifg_geotiff.lower.return_value = "yes"
    ic_mock.ifg_off.exists.return_value = False

    # finally run the workflow :-)
    process_ifg.run_workflow(pc_mock, ic_mock, dc_mock, ifg_width=204, clean_up=True)

    # check some of the funcs in each step are called
    assert m_pygamma.create_offset.called
    assert m_pygamma.base_orbit.called
    assert m_pygamma.multi_cpx.called
    assert m_pygamma.adf.called
    assert m_pygamma.rascc_mask.called
    assert m_pygamma.interp_ad.called
    assert m_pygamma.data2geotiff.called
    assert remove_mock.call_count > 10
    assert subprocess_mock.run.called


def test_run_workflow_missing_r_master_slc(ic_mock):
    ic_mock.r_master_slc.exists.return_value = False

    with pytest.raises(ProcessIfgException):
        process_ifg.run_workflow(pc_mock, ic_mock, dc_mock, ifg_width=10, clean_up=True)


def test_run_workflow_missing_r_master_mli(ic_mock):
    ic_mock.r_master_slc.exists.return_value = True
    ic_mock.r_master_mli.exists.return_value = False

    with pytest.raises(ProcessIfgException):
        process_ifg.run_workflow(pc_mock, ic_mock, dc_mock, ifg_width=11, clean_up=True)


def test_run_workflow_missing_r_slave_slc(ic_mock):
    ic_mock.r_master_slc.exists.return_value = True
    ic_mock.r_master_mli.exists.return_value = True
    ic_mock.r_slave_slc.exists.return_value = False

    with pytest.raises(ProcessIfgException):
        process_ifg.run_workflow(pc_mock, ic_mock, dc_mock, ifg_width=12, clean_up=True)


def test_run_workflow_missing_r_slave_mli(ic_mock):
    ic_mock.r_master_slc.exists.return_value = True
    ic_mock.r_master_mli.exists.return_value = True
    ic_mock.r_slave_slc.exists.return_value = True
    ic_mock.r_slave_mli.exists.return_value = False

    with pytest.raises(ProcessIfgException):
        process_ifg.run_workflow(pc_mock, ic_mock, dc_mock, ifg_width=13, clean_up=True)


def test_get_ifg_width():
    # content from gadi:/g/data/dg9/INSAR_ANALYSIS/CAMDEN/S1/GAMMA/T147D/SLC/20200105/r20200105_VV_8rlks.mli.par
    c = "line_header_size:                  0\nrange_samples:                  8630\nazimuth_lines:                85\n"
    config = io.StringIO(c)
    assert process_ifg.get_ifg_width(config) == 8630


def test_get_ifg_width_not_found():
    config = io.StringIO("Fake line 0\nFake line 1\nFake line 2\n")
    with pytest.raises(ProcessIfgException):
        process_ifg.get_ifg_width(config)


def test_calc_int(monkeypatch, pg_int_mock, pc_mock, ic_mock):
    """Verify default path through the INT processing step without cleanup."""

    # craftily substitute the 'pg' py_gamma obj for a mock: avoids a missing import when testing
    # locally, or calling the real thing on Gadi...
    # TODO: monkeypatch or use unittest.mock's patch? Which is better?
    monkeypatch.setattr(process_ifg, "pg", pg_int_mock)

    ic_mock.ifg_off = mock.Mock(spec=pathlib.Path)
    ic_mock.ifg_off.exists.return_value = False  # offset not yet processed

    process_ifg.calc_int(pc_mock, ic_mock, clean_up=False)

    assert pg_int_mock.create_offset.called

    # ensure CSK sensor block / SP mode section is skipped
    assert pg_int_mock.init_offset_orbit.called is False
    assert pg_int_mock.init_offset.called is False

    # check the core processing was called
    assert pg_int_mock.offset_pwr.called
    assert pg_int_mock.offset_fit.called
    assert pg_int_mock.create_diff_par.called


def test_calc_int_with_cleanup(monkeypatch, pg_int_mock, pc_mock, ic_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_int_mock)

    ic_mock.ifg_off = mock.Mock(spec=pathlib.Path)
    ic_mock.ifg_off.exists.return_value = True  # simulate offset already processed

    ic_mock.ifg_offs = mock.Mock(spec=pathlib.Path)
    ic_mock.ifg_ccp = mock.Mock(spec=pathlib.Path)
    ic_mock.ifg_coffs = mock.Mock(spec=pathlib.Path)
    ic_mock.ifg_coffsets = mock.Mock(spec=pathlib.Path)

    assert ic_mock.ifg_offs.unlink.called is False
    assert ic_mock.ifg_ccp.unlink.called is False
    assert ic_mock.ifg_coffs.unlink.called is False
    assert ic_mock.ifg_coffsets.unlink.called is False

    process_ifg.calc_int(pc_mock, ic_mock, clean_up=True)

    assert ic_mock.ifg_offs.unlink.called
    assert ic_mock.ifg_ccp.unlink.called
    assert ic_mock.ifg_coffs.unlink.called
    assert ic_mock.ifg_coffsets.unlink.called


def test_error_handling_decorator(monkeypatch, subprocess_mock):
    # force all fake subprocess calls to fail
    subprocess_mock.run.return_value = -1

    pgi = py_gamma_ga.GammaInterface(
        install_dir="./fake-install",
        gamma_exes={"create_offset": "fake-EXE-name"},
        subprocess_func=process_ifg.decorator(subprocess_mock),
    )

    # ensure mock logger has all core error(), msg() etc logging functions
    log_mock = mock.Mock(spec=structlog.stdlib.BoundLogger)
    assert log_mock.error.called is False
    monkeypatch.setattr(process_ifg, "_LOG", log_mock)

    with pytest.raises(ProcessIfgException):
        pgi.create_offset(1, 2, 3, key="value")

    assert log_mock.error.called
    has_cout = has_cerr = False

    for c in log_mock.error.call_args:
        if const.COUT in c:
            has_cout = True

        if const.CERR in c:
            has_cerr = True

    assert has_cout
    assert has_cerr


@pytest.fixture
def pg_flat_mock():
    """Create basic mock of the py_gamma module for the INT processing step."""
    pg_mock = mock.Mock()
    ret = (0, "cout-fake-content", "cerr-fake-content")
    pg_mock.base_orbit.return_value = ret
    pg_mock.phase_sim_orb.return_value = ret
    pg_mock.SLC_diff_intf.return_value = ret
    pg_mock.base_init.return_value = ret
    pg_mock.base_add.return_value = ret
    pg_mock.phase_sim.return_value = ret

    pg_mock.gcp_phase.return_value = ret
    pg_mock.sub_phase.return_value = ret
    pg_mock.mcf.return_value = ret
    pg_mock.base_ls.return_value = ret
    pg_mock.cc_wave.return_value = ret
    pg_mock.rascc_mask.return_value = ret
    pg_mock.multi_cpx.return_value = ret
    pg_mock.multi_real.return_value = ret
    pg_mock.base_perp.return_value = ret
    pg_mock.extract_gcp.return_value = ret
    return pg_mock


@pytest.fixture
def dc_mock():
    """Default mock for DEMFileNames config."""
    dcm = mock.Mock(spec=DEMFileNames)
    return dcm


def test_generate_init_flattened_ifg(
    monkeypatch, pg_flat_mock, pc_mock, ic_mock, dc_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_flat_mock)

    assert pg_flat_mock.base_orbit.called is False
    assert pg_flat_mock.phase_sim_orb.called is False
    assert pg_flat_mock.SLC_diff_intf.called is False
    assert pg_flat_mock.base_init.called is False
    assert pg_flat_mock.base_add.called is False
    assert pg_flat_mock.phase_sim.called is False

    process_ifg.generate_init_flattened_ifg(pc_mock, ic_mock, dc_mock, clean_up=False)

    assert pg_flat_mock.base_orbit.called
    assert pg_flat_mock.phase_sim_orb.called
    assert pg_flat_mock.SLC_diff_intf.call_count == 2
    assert pg_flat_mock.base_init.called
    assert pg_flat_mock.base_add.called
    assert pg_flat_mock.phase_sim.called


def test_generate_final_flattened_ifg(
    monkeypatch, pg_flat_mock, pc_mock, ic_mock, dc_mock
):
    # test refinement of baseline model using ground control points
    monkeypatch.setattr(process_ifg, "pg", pg_flat_mock)

    assert pg_flat_mock.multi_cpx.called is False
    assert pg_flat_mock.cc_wave.called is False
    assert pg_flat_mock.rascc_mask.called is False
    assert pg_flat_mock.mcf.called is False
    assert pg_flat_mock.multi_real.called is False
    assert pg_flat_mock.sub_phase.called is False
    assert pg_flat_mock.extract_gcp.called is False
    assert pg_flat_mock.gcp_phase.called is False
    assert pg_flat_mock.base_ls.called is False
    assert pg_flat_mock.phase_sim.called is False
    assert pg_flat_mock.SLC_diff_intf.called is False
    assert pg_flat_mock.base_perp.called is False

    fake_width10 = 400
    m_get_width10 = mock.Mock(return_value=fake_width10)
    monkeypatch.setattr(process_ifg, "get_width10", m_get_width10)

    fake_ifg_width = 99
    process_ifg.generate_final_flattened_ifg(
        pc_mock, ic_mock, dc_mock, fake_ifg_width, clean_up=False
    )

    assert pg_flat_mock.multi_cpx.called
    assert pg_flat_mock.cc_wave.call_count == 3
    assert pg_flat_mock.rascc_mask.call_count == 2
    assert pg_flat_mock.mcf.called
    assert pg_flat_mock.multi_real.called
    assert pg_flat_mock.sub_phase.call_count == 2
    assert pg_flat_mock.extract_gcp.called
    assert pg_flat_mock.gcp_phase.called
    assert pg_flat_mock.base_ls.called
    assert pg_flat_mock.phase_sim.called
    assert pg_flat_mock.SLC_diff_intf.called
    assert pg_flat_mock.base_perp.call_count == 1


def test_generate_final_flattened_ifg_bperp_write_fail(
    monkeypatch, pg_flat_mock, pc_mock, ic_mock, dc_mock
):
    monkeypatch.setattr(process_ifg, "get_width10", lambda _: 52)
    monkeypatch.setattr(process_ifg, "pg", pg_flat_mock)
    ic_mock.ifg_bperp.open.side_effect = IOError("Simulated ifg_bperp failure")

    with pytest.raises(IOError):
        fake_ifg_width = 99
        process_ifg.generate_final_flattened_ifg(
            pc_mock, ic_mock, dc_mock, fake_ifg_width, clean_up=False
        )


def _get_mock_file_and_path(fake_content):
    """
    Helper function to mock out pathlib.Path.open() and file.readlines()
    :param fake_content: Sequence of values for file.readlines() to emit
    :return: (file_mock, path_mock)
    """
    # file like object to be returned from context manager
    m_file = mock.MagicMock()
    m_file.readlines.return_value = fake_content

    # TRICKY: mock chain of open() calls, context manager etc to return custom file mock
    m_path = mock.MagicMock(spec=pathlib.Path)
    m_path.open.return_value.__enter__.return_value = m_file
    return m_file, m_path


def test_get_width10():
    _, m_path = _get_mock_file_and_path(
        ["a    1\n", "interferogram_width:         43\n", "b         24\n"]
    )
    width = process_ifg.get_width10(m_path)
    assert width == 43, "got {}".format(width)


def test_get_width10_not_found():
    _, m_path = _get_mock_file_and_path(["fake1    1\n", "fake2    2\n"])

    with pytest.raises(ProcessIfgException):
        process_ifg.get_width10(m_path)


@pytest.fixture
def pg_filt_mock():
    """Create basic mock of the py_gamma module for the INT processing step."""
    pgm = mock.Mock()
    pgm.adf.return_value = 0
    return pgm


def test_calc_filt(monkeypatch, pg_filt_mock, pc_mock, ic_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_filt_mock)

    ic_mock.ifg_flat = mock.Mock()
    ic_mock.ifg_flat.exists.return_value = True

    assert pg_filt_mock.adf.called is False
    process_ifg.calc_filt(pc_mock, ic_mock, ifg_width=230)
    assert pg_filt_mock.adf.called


def test_calc_filt_no_flat_file(monkeypatch, pg_filt_mock, pc_mock, ic_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_filt_mock)

    ic_mock.ifg_flat = mock.Mock()
    ic_mock.ifg_flat.exists.return_value = False

    with pytest.raises(ProcessIfgException):
        process_ifg.calc_filt(pc_mock, ic_mock, ifg_width=180)


@pytest.fixture
def pg_unw_mock():
    pgm = mock.Mock()
    pgm.rascc_mask.return_value = 0
    pgm.rascc_mask_thinning.return_value = 0
    pgm.mcf.return_value = 0
    pgm.interp_ad.return_value = 0
    pgm.unw_model.return_value = 0
    pgm.mask_data.return_value = 0
    return pgm


def test_calc_unw(monkeypatch, pg_unw_mock, pc_mock, ic_mock):
    # NB: (m)looks will always be 2 for Sentinel-1 ARD product generation
    monkeypatch.setattr(process_ifg, "pg", pg_unw_mock)

    # ignore the thinning step as it will be tested separately
    m_thin = mock.Mock()
    monkeypatch.setattr(process_ifg, "calc_unw_thinning", m_thin)

    pc_mock.ifg_unw_mask = "no"
    fake_ifg_width = 13

    assert pg_unw_mock.rascc_mask.called is False
    assert m_thin.called is False
    assert pg_unw_mock.mask_data.called is False

    process_ifg.calc_unw(pc_mock, ic_mock, fake_ifg_width, clean_up=False)

    assert pg_unw_mock.rascc_mask.called
    assert m_thin.called
    assert pg_unw_mock.mask_data.called is False


def test_calc_unw_no_ifg_filt(monkeypatch, pg_unw_mock, pc_mock, ic_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_unw_mock)
    ic_mock.ifg_filt.exists.return_value = False

    with pytest.raises(ProcessIfgException):
        process_ifg.calc_unw(pc_mock, ic_mock, ifg_width=101, clean_up=False)


def test_calc_unw_with_mask(monkeypatch, pg_unw_mock, pc_mock, ic_mock, remove_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_unw_mock)
    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)
    pc_mock.ifg_unw_mask = "yes"

    assert pg_unw_mock.mask_data.called is False
    assert remove_mock.called is False

    process_ifg.calc_unw(pc_mock, ic_mock, ifg_width=202, clean_up=False)

    assert pg_unw_mock.mask_data.called is True
    assert remove_mock.called is True


def test_calc_unw_mlooks_over_threshold_not_implemented(
    monkeypatch, pg_unw_mock, pc_mock, ic_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_unw_mock)
    pc_mock.multi_look = 5

    with pytest.raises(NotImplementedError):
        process_ifg.calc_unw(pc_mock, ic_mock, ifg_width=15, clean_up=False)


def test_calc_unw_thinning(monkeypatch, pg_unw_mock, pc_mock, ic_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_unw_mock)

    assert pg_unw_mock.rascc_mask_thinning.called is False
    assert pg_unw_mock.mcf.called is False
    assert pg_unw_mock.interp_ad.called is False
    assert pg_unw_mock.unw_model.called is False

    process_ifg.calc_unw_thinning(pc_mock, ic_mock, ifg_width=17, clean_up=False)

    assert pg_unw_mock.rascc_mask_thinning.called
    assert pg_unw_mock.mcf.called
    assert pg_unw_mock.interp_ad.called
    assert pg_unw_mock.unw_model.called


@pytest.fixture
def pg_geocode_mock():
    """Basic mock for pygamma calls in GEOCODE"""
    pgm = mock.Mock()
    ret = (0, ["cout for pg_geocode_mock"], ["cerr for pg_geocode_mock"])

    pgm.geocode_back.return_value = ret
    pgm.mask_data.return_value = ret
    pgm.convert.return_value = ret
    pgm.kml_map.return_value = ret
    pgm.cpx_to_real.return_value = ret
    pgm.rascc.return_value = ret
    pgm.ras2ras.return_value = ret
    pgm.rasrmg.return_value = ret
    pgm.data2geotiff.return_value = ret
    return pgm


# TODO: can fixtures call other fixtures to get their setup? (e.g. mock pg inside another fixture?)
def test_geocode_unwrapped_ifg(
    monkeypatch, ic_mock, dc_mock, pg_geocode_mock, remove_mock, subprocess_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)

    # patch at the subprocess level for testing this part of convert() in geocode step
    subprocess_mock.run.return_value = 0
    monkeypatch.setattr(process_ifg, "subprocess", subprocess_mock)

    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    assert pg_geocode_mock.geocode_back.called is False
    assert pg_geocode_mock.mask_data.called is False
    assert pg_geocode_mock.rasrmg.called is False
    assert pg_geocode_mock.kml_map.called is False

    assert subprocess_mock.run.called is False
    assert remove_mock.called is False

    width_in, width_out = 5, 7  # fake values
    process_ifg.geocode_unwrapped_ifg(ic_mock, dc_mock, width_in, width_out)

    assert pg_geocode_mock.geocode_back.called
    assert pg_geocode_mock.mask_data.called
    assert pg_geocode_mock.rasrmg.called
    assert pg_geocode_mock.kml_map.called

    assert subprocess_mock.run.called
    assert remove_mock.called


def test_geocode_flattened_ifg(
    monkeypatch, ic_mock, dc_mock, pg_geocode_mock, remove_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)

    # patch convert function for testing this part of geocode step
    m_convert = mock.Mock(spec=process_ifg.convert)
    monkeypatch.setattr(process_ifg, "convert", m_convert)

    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    assert pg_geocode_mock.cpx_to_real.called is False
    assert pg_geocode_mock.geocode_back.called is False
    assert pg_geocode_mock.mask_data.called is False
    assert pg_geocode_mock.rasrmg.called is False
    assert pg_geocode_mock.kml_map.called is False
    assert m_convert.called is False
    assert remove_mock.called is False

    width_in, width_out = 9, 13  # fake values
    process_ifg.geocode_flattened_ifg(ic_mock, dc_mock, width_in, width_out)

    assert pg_geocode_mock.cpx_to_real.called
    assert pg_geocode_mock.geocode_back.called
    assert pg_geocode_mock.mask_data.called
    assert pg_geocode_mock.rasrmg.called
    assert pg_geocode_mock.kml_map.called
    assert m_convert.called
    assert remove_mock.called


def test_geocode_filtered_ifg(
    monkeypatch, ic_mock, dc_mock, pg_geocode_mock, remove_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)

    # patch convert function for testing this part of geocode step
    m_convert = mock.Mock(spec=process_ifg.convert)
    monkeypatch.setattr(process_ifg, "convert", m_convert)

    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    assert pg_geocode_mock.cpx_to_real.called is False
    assert pg_geocode_mock.geocode_back.called is False
    assert pg_geocode_mock.mask_data.called is False
    assert pg_geocode_mock.rasrmg.called is False
    assert pg_geocode_mock.kml_map.called is False
    assert m_convert.called is False
    assert remove_mock.called is False

    width_in, width_out = 15, 19  # fake values
    process_ifg.geocode_filtered_ifg(ic_mock, dc_mock, width_in, width_out)

    assert pg_geocode_mock.cpx_to_real.called
    assert pg_geocode_mock.geocode_back.called
    assert pg_geocode_mock.mask_data.called
    assert pg_geocode_mock.rasrmg.called
    assert pg_geocode_mock.kml_map.called
    assert m_convert.called
    assert remove_mock.called


def test_geocode_flat_coherence_file(
    monkeypatch, ic_mock, dc_mock, pg_geocode_mock, remove_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)

    # patch convert function for testing this part of geocode step
    m_convert = mock.Mock(spec=process_ifg.convert)
    monkeypatch.setattr(process_ifg, "convert", m_convert)

    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    assert pg_geocode_mock.geocode_back.called is False
    assert pg_geocode_mock.rascc.called is False
    assert pg_geocode_mock.ras2ras.called is False
    assert pg_geocode_mock.kml_map.called is False
    assert m_convert.called is False

    width_in, width_out = 33, 37  # fake values
    process_ifg.geocode_flat_coherence_file(ic_mock, dc_mock, width_in, width_out)

    assert pg_geocode_mock.geocode_back.called
    assert pg_geocode_mock.rascc.called
    assert pg_geocode_mock.ras2ras.called
    assert pg_geocode_mock.kml_map.called
    assert m_convert.called


def test_geocode_filtered_coherence_file(
    monkeypatch, ic_mock, dc_mock, pg_geocode_mock, remove_mock
):
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)

    m_convert = mock.Mock(spec=process_ifg.convert)
    monkeypatch.setattr(process_ifg, "convert", m_convert)

    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    assert pg_geocode_mock.geocode_back.called is False
    assert pg_geocode_mock.rascc.called is False
    assert pg_geocode_mock.ras2ras.called is False
    assert pg_geocode_mock.kml_map.called is False
    assert m_convert.called is False

    width_in, width_out = 43, 31  # fake values
    process_ifg.geocode_filtered_coherence_file(ic_mock, dc_mock, width_in, width_out)

    assert pg_geocode_mock.geocode_back.called
    assert pg_geocode_mock.rascc.called
    assert pg_geocode_mock.ras2ras.called
    assert pg_geocode_mock.kml_map.called
    assert m_convert.called


def test_do_geocode(monkeypatch, pc_mock, ic_mock, dc_mock, pg_geocode_mock, remove_mock):
    """Test the full geocode step"""
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)

    pc_mock.ifg_geotiff.lower.return_value = "yes"

    # mock the width config file readers
    m_width_in = mock.Mock(return_value=22)
    m_width_out = mock.Mock(return_value=11)
    monkeypatch.setattr(process_ifg, "get_width_in", m_width_in)
    monkeypatch.setattr(process_ifg, "get_width_out", m_width_out)

    # mock individual processing blocks as they're tested elsewhere
    m_geocode_unwrapped_ifg = mock.Mock()
    m_geocode_flattened_ifg = mock.Mock()
    m_geocode_filtered_ifg = mock.Mock()
    m_geocode_flat_coherence_file = mock.Mock()
    m_geocode_filtered_coherence_file = mock.Mock()

    monkeypatch.setattr(process_ifg, "geocode_unwrapped_ifg", m_geocode_unwrapped_ifg)
    monkeypatch.setattr(process_ifg, "geocode_flattened_ifg", m_geocode_flattened_ifg)
    monkeypatch.setattr(process_ifg, "geocode_filtered_ifg", m_geocode_filtered_ifg)
    monkeypatch.setattr(
        process_ifg, "geocode_flat_coherence_file", m_geocode_flat_coherence_file
    )
    monkeypatch.setattr(
        process_ifg, "geocode_filtered_coherence_file", m_geocode_filtered_coherence_file
    )
    monkeypatch.setattr(process_ifg, "remove_files", remove_mock)

    process_ifg.do_geocode(pc_mock, ic_mock, dc_mock)

    assert m_width_in.called
    assert m_width_out.called
    assert m_geocode_unwrapped_ifg.called
    assert m_geocode_flattened_ifg.called
    assert m_geocode_filtered_ifg.called
    assert m_geocode_flat_coherence_file.called
    assert m_geocode_filtered_ifg.called

    assert pg_geocode_mock.data2geotiff.call_count == 5
    assert remove_mock.call_count == len(const.TEMP_FILE_GLOBS)


def test_do_geocode_no_geotiff(monkeypatch, pc_mock, ic_mock, dc_mock, pg_geocode_mock):
    monkeypatch.setattr(process_ifg, "pg", pg_geocode_mock)
    pc_mock.ifg_geotiff.lower.return_value = "no"
    monkeypatch.setattr(process_ifg, "get_width_in", mock.Mock(return_value=32))
    monkeypatch.setattr(process_ifg, "get_width_out", mock.Mock(return_value=31))

    monkeypatch.setattr(process_ifg, "geocode_unwrapped_ifg", mock.Mock())
    monkeypatch.setattr(process_ifg, "geocode_flattened_ifg", mock.Mock())
    monkeypatch.setattr(process_ifg, "geocode_filtered_ifg", mock.Mock())
    monkeypatch.setattr(process_ifg, "geocode_flat_coherence_file", mock.Mock())
    monkeypatch.setattr(process_ifg, "geocode_filtered_coherence_file", mock.Mock())

    process_ifg.do_geocode(pc_mock, ic_mock, dc_mock)

    assert pg_geocode_mock.data2geotiff.called is False


def test_get_width_in():
    config = io.StringIO("Fake line\nrange_samp_1: 45\nAnother fake\n")
    assert process_ifg.get_width_in(config) == 45


def test_get_width_in_not_found():
    config = io.StringIO("Fake line 0\nFake line 1\nFake line 2\n")
    with pytest.raises(ProcessIfgException):
        process_ifg.get_width_in(config)


def test_get_width_out():
    config = io.StringIO("Fake line\nwidth: 32\nAnother fake\n")
    assert process_ifg.get_width_out(config) == 32


def test_get_width_out_not_found():
    config = io.StringIO("Fake line 0\nFake line 1\nFake line 2\n")
    with pytest.raises(ProcessIfgException):
        process_ifg.get_width_out(config)


def test_convert(monkeypatch):
    m_file = mock.Mock()
    m_run = mock.Mock(return_value=0)
    monkeypatch.setattr(process_ifg.subprocess, "run", m_run)

    assert m_run.called is False
    process_ifg.convert(m_file)
    assert m_run.called is True


def test_convert_subprocess_exception(monkeypatch):
    m_file = mock.Mock()
    m_run = mock.Mock(
        side_effect=subprocess.CalledProcessError(returncode=-1, cmd="Fake_cmd")
    )
    monkeypatch.setattr(process_ifg.subprocess, "run", m_run)

    with pytest.raises(subprocess.CalledProcessError):
        process_ifg.convert(m_file)


def test_remove_files_empty_path():
    process_ifg.remove_files("")  # should pass quietly


def test_remove_files_with_error(monkeypatch):
    m_file_not_found = mock.Mock()
    m_file_not_found.unlink.side_effect = FileNotFoundError("Fake File Not Found")

    m_log = mock.Mock()
    monkeypatch.setattr(process_ifg, "_LOG", m_log)

    # file not found should be logged but ignored
    process_ifg.remove_files(m_file_not_found)
    assert m_log.error.called
