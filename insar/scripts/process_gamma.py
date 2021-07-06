#!/usr/bin/env python

import datetime
import os
import re
import traceback
import os.path
from os.path import exists, join as pjoin
from pathlib import Path
from typing import List
import luigi
import luigi.configuration
import logging
import logging.config
import pandas as pd
from luigi.util import requires
import structlog
import shutil
import osgeo.gdal
import json
import pkg_resources
import geopandas
import pkg_resources
import geopandas

import insar
from insar.constant import SCENE_DATE_FMT, SlcFilenames, MliFilenames
from insar.generate_slc_inputs import query_slc_inputs, slc_inputs
from insar.calc_baselines_new import BaselineProcess
from insar.calc_multilook_values import multilook, calculate_mean_look_values
from insar.coregister_dem import CoregisterDem
from insar.coregister_slc import CoregisterSlc
from insar.make_gamma_dem import create_gamma_dem
from insar.process_s1_slc import SlcProcess
from insar.process_ifg import run_workflow, get_ifg_width, TempFileConfig, validate_ifg_input_files, ProcessIfgException
from insar.project import ProcConfig, DEMFileNames, IfgFileNames, ARDWorkflow
from insar.process_backscatter import generate_normalised_backscatter

from insar.meta_data.s1_slc import S1DataDownload
from insar.logs import TASK_LOGGER, STATUS_LOGGER, COMMON_PROCESSORS

structlog.configure(processors=COMMON_PROCESSORS)
_LOG = structlog.get_logger("insar")

__RAW__ = "RAW_DATA"
__SLC__ = "SLC"
__DEM_GAMMA__ = "GAMMA_DEM"
__DEM__ = "DEM"
__IFG__ = "IFG"
__DATE_FMT__ = "%Y%m%d"
__TRACK_FRAME__ = r"^T[0-9][0-9]?[0-9]?[A|D]_F[0-9][0-9]?"

SLC_PATTERN = (
    r"^(?P<sensor>S1[AB])_"
    r"(?P<beam>S1|S2|S3|S4|S5|S6|IW|EW|WV|EN|N1|N2|N3|N4|N5|N6|IM)_"
    r"(?P<product>SLC|GRD|OCN)(?:F|H|M|_)_"
    r"(?:1|2)"
    r"(?P<category>S|A)"
    r"(?P<pols>SH|SV|DH|DV|VV|HH|HV|VH)_"
    r"(?P<start>[0-9]{8}T[0-9]{6})_"
    r"(?P<stop>[0-9]{8}T[0-9]{6})_"
    r"(?P<orbitNumber>[0-9]{6})_"
    r"(?P<dataTakeID>[0-9A-F]{6})_"
    r"(?P<productIdentifier>[0-9A-F]{4})"
    r"(?P<extension>.SAFE|.zip)$"
)


@luigi.Task.event_handler(luigi.Event.FAILURE)
def on_failure(task, exception):
    """Capture any Task Failure here."""
    TASK_LOGGER.exception(
        "Task failed",
        task=task.get_task_family(),
        params=task.to_str_params(),
        track=getattr(task, "track", ""),
        frame=getattr(task, "frame", ""),
        stack_info=True,
        status="failure",
        exception=exception.__str__(),
        traceback=traceback.format_exc().splitlines(),
    )


@luigi.Task.event_handler(luigi.Event.SUCCESS)
def on_success(task):
    """Capture any Task Succes here."""
    TASK_LOGGER.info(
        "Task succeeded",
        task=task.get_task_family(),
        params=task.to_str_params(),
        track=getattr(task, "track", ""),
        frame=getattr(task, "frame", ""),
        status="success",
    )


# TODO: This should take a primary polarisation to filter on
def get_scenes(burst_data_csv):
    df = pd.read_csv(burst_data_csv)
    scene_dates = [_dt for _dt in sorted(df.date.unique())]

    frames_data = []

    for _date in scene_dates:
        df_subset = df[df["date"] == _date]
        polarizations = df_subset.polarization.unique()
        # TODO: This filter should be to primary polarisation
        # (which is not necessarily polarizations[0])
        df_subset_new = df_subset[df_subset["polarization"] == polarizations[0]]

        complete_frame = True
        for swath in [1, 2, 3]:
            swath_df = df_subset_new[df_subset_new.swath == "IW{}".format(swath)]
            swath_df = swath_df.sort_values(by="acquistion_datetime", ascending=True)
            for row in swath_df.itertuples():
                missing_bursts = row.missing_primary_bursts.strip("][")
                if missing_bursts:
                    complete_frame = False

        # HACK: Until we implement https://github.com/GeoscienceAustralia/gamma_insar/issues/200
        # - this simply refuses to present any scene with missing bursts to the luigi workflow
        assert(complete_frame)

        dt = datetime.datetime.strptime(_date, "%Y-%m-%d")
        frames_data.append((dt, complete_frame, polarizations))

    return frames_data


def find_scenes_in_range(
    primary_dt, date_list, thres_days: int, include_closest: bool = True
):
    """
    Creates a list of frame dates that within range of a primary date.

    :param primary_dt:
        The primary date in which we are searching for scenes relative to.
    :param date_list:
        The list which we're searching for dates in.
    :param thres_days:
        The number of days threshold in which scenes must be within relative to
        the primary date.
    :param include_closest:
        When true - if there exist slc frames on either side of the primary date, which are NOT
        within the threshold window then the closest date from each side will be
        used instead of no scene at all.
    """

    # We do everything with datetime.date's (can't mix and match date vs. datetime)
    if isinstance(primary_dt, datetime.datetime):
        primary_dt = primary_dt.date()
    elif not isinstance(primary_dt, datetime.date):
        primary_dt = datetime.date(primary_dt)

    thresh_dt = datetime.timedelta(days=thres_days)
    tree_lhs = []  # This was the 'lower' side in the bash...
    tree_rhs = []  # This was the 'upper' side in the bash...
    closest_lhs = None
    closest_rhs = None
    closest_lhs_diff = None
    closest_rhs_diff = None

    for dt in date_list:
        if isinstance(dt, datetime.datetime):
            dt = dt.date()
        elif not isinstance(primary_dt, datetime.date):
            dt = datetime.date(dt)

        dt_diff = dt - primary_dt

        # Skip scenes that match the primary date
        if dt_diff.days == 0:
            continue

        # Record closest scene
        if dt_diff < datetime.timedelta(0):
            is_closer = closest_lhs is None or dt_diff > closest_lhs_diff
            closest_lhs = dt if is_closer else closest_lhs
            closest_lhs_diff = dt_diff
        else:
            is_closer = closest_rhs is None or dt_diff < closest_rhs_diff
            closest_rhs = dt if is_closer else closest_rhs
            closest_rhs_diff = dt_diff

        # Skip scenes outside threshold window
        if abs(dt_diff) > thresh_dt:
            continue

        if dt_diff < datetime.timedelta(0):
            tree_lhs.append(dt)
        else:
            tree_rhs.append(dt)

    # Use closest scene if none are in threshold window
    if include_closest:
        if len(tree_lhs) == 0 and closest_lhs is not None:
            _LOG.info(
                f"Date difference to closest secondary greater than {thres_days} days, using closest secondary only: {closest_lhs}"
            )
            tree_lhs = [closest_lhs]

        if len(tree_rhs) == 0 and closest_rhs is not None:
            _LOG.info(
                f"Date difference to closest secondary greater than {thres_days} days, using closest secondary only: {closest_rhs}"
            )
            tree_rhs = [closest_rhs]

    return tree_lhs, tree_rhs


def create_secondary_coreg_tree(primary_dt, date_list, thres_days=63):
    """
    Creates a set of co-registration lists containing subsets of the prior set, to create a tree-like co-registration structure.

    Notes from the bash on :thres_days: parameter:
        #thres_days=93 # three months, S1A/B repeats 84, 90, 96, ... (90 still ok, 96 too long)
        # -> some secondaries with zero averages for azimuth offset refinement
        thres_days=63 # three months, S1A/B repeats 54, 60, 66, ... (60 still ok, 66 too long)
         -> 63 days seems to be a good compromise between runtime and coregistration success
        #thres_days=51 # maximum 7 weeks, S1A/B repeats 42, 48, 54, ... (48 still ok, 54 too long)
        # -> longer runtime compared to 63, similar number of badly coregistered scenes
        # do secondaries with time difference less than thres_days
    """

    # We do everything with datetime.date's (can't mix and match date vs. datetime)
    if isinstance(primary_dt, datetime.datetime):
        primary_dt = primary_dt.date()
    elif not isinstance(primary_dt, datetime.date):
        primary_dt = datetime.date(primary_dt)

    lists = []

    # Note: when compositing the lists, rhs comes first because the bash puts the rhs as
    # the "lower" part of the tree, which seems to appear first in the list file...
    #
    # I've opted for rhs vs. lhs because it's more obvious, newer scenes are to the right
    # in sequence as they're greater than, older scenes are to the left / less than.

    # Initial Primary<->Secondary coreg list
    lhs, rhs = find_scenes_in_range(primary_dt, date_list, thres_days)
    last_list = lhs + rhs

    while len(last_list) > 0:
        lists.append(last_list)

        if last_list[0] < primary_dt:
            lhs, rhs = find_scenes_in_range(last_list[0], date_list, thres_days)
            sub_list1 = lhs
        else:
            sub_list1 = []

        if last_list[-1] > primary_dt:
            lhs, rhs = find_scenes_in_range(last_list[-1], date_list, thres_days)
            sub_list2 = rhs
        else:
            sub_list2 = []

        last_list = sub_list1 + sub_list2

    return lists


def get_coreg_date_pairs(outdir: Path, proc_config: ProcConfig):
    list_dir = outdir / proc_config.list_dir
    primary_scene = read_primary_date(outdir).strftime(__DATE_FMT__)

    pairs = []

    for secondaries_list in list_dir.glob("secondaries*.list"):
        list_index = int(secondaries_list.stem[11:])
        prev_list_idx = list_index - 1

        with secondaries_list.open("r") as file:
            list_date_strings = file.read().splitlines()

        # The first tier of the tree is always coregistered to primary ref date
        if list_index == 1:
            pairs += [(primary_scene, dt) for dt in list_date_strings]

        # All the rest coregister to
        else:
            for slc_scene in list_date_strings:
                if int(slc_scene) < int(proc_config.ref_primary_scene):
                    coreg_ref_scene = read_file_line(list_dir / f'secondaries{prev_list_idx}.list', 0)
                elif int(slc_scene) > int(proc_config.ref_primary_scene):
                    coreg_ref_scene = read_file_line(list_dir / f'secondaries{prev_list_idx}.list', -1)
                else:  # slc_scene == primary_scene
                    continue

            pairs.append((coreg_ref_scene, slc_scene))

    return pairs


def read_file_line(filepath, line: int):
    """Reads a specific line from a text file"""
    with Path(filepath).open('r') as file:
        return file.read().splitlines()[line]


def calculate_primary(scenes_list) -> datetime:
    slc_dates = [
        datetime.datetime.strptime(scene.strip(), __DATE_FMT__).date()
        for scene in scenes_list
    ]
    return sorted(slc_dates, reverse=True)[int(len(slc_dates) / 2)]


def read_primary_date(outdir: Path):
    with (outdir / 'lists' / 'primary_ref_scene').open() as f:
        date = f.readline().strip()

    return datetime.datetime.strptime(date, __DATE_FMT__).date()


class ExternalFileChecker(luigi.ExternalTask):
    """checks the external dependencies."""

    filename = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(str(self.filename))


class ListParameter(luigi.Parameter):
    """Converts luigi parameters separated by comma to a list."""

    def parse(self, arguments):
        return arguments.split(",")


def _forward_kwargs(cls, kwargs):
    ids = cls.get_param_names()

    return {k:v for k,v in kwargs.items() if k in ids}


def mk_clean_dir(path: Path):
    # Clear directory in case it has incomplete data from an interrupted run we've resumed
    if path.exists():
        shutil.rmtree(path)

    path.mkdir(parents=True, exist_ok=True)


def read_rlks_alks(ml_file: Path):
    with ml_file.open("r") as src:
        for line in src.readlines():
            if line.startswith("rlks"):
                rlks = int(line.strip().split(":")[1])
            if line.startswith("alks"):
                alks = int(line.strip().split(":")[1])

    return rlks, alks


class SlcDataDownload(luigi.Task):
    """
    Downloads/copies the raw data for an SLC scene, for all requested polarisations.
    """

    slc_scene = luigi.Parameter()
    poeorb_path = luigi.Parameter()
    resorb_path = luigi.Parameter()
    output_dir = luigi.Parameter()
    polarization = luigi.ListParameter()
    workdir = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(str(self.workdir)).joinpath(
                f"{Path(str(self.slc_scene)).stem}_slc_download.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(slc_scene=self.slc_scene)

        download_obj = S1DataDownload(
            Path(str(self.slc_scene)),
            list(self.polarization),
            Path(str(self.poeorb_path)),
            Path(str(self.resorb_path)),
        )
        failed = False

        outdir = Path(self.output_dir)
        outdir.mkdir(parents=True, exist_ok=True)

        try:
            download_obj.slc_download(outdir)
        except:
            log.error("SLC download failed with exception", exc_info=True)
            failed = True
        finally:
            with self.output().open("w") as f:
                if failed:
                    f.write(f"{Path(self.slc_scene).name}")
                else:
                    f.write("")


class InitialSetup(luigi.Task):
    """
    Runs the initial setup of insar processing workflow by
    creating required directories and file lists
    """

    proc_file = luigi.Parameter()
    start_date = luigi.Parameter()
    end_date = luigi.Parameter()
    shape_file = luigi.Parameter()
    orbit = luigi.Parameter()
    sensor = luigi.Parameter()
    polarization = luigi.ListParameter(default=["VV"])
    track = luigi.Parameter()
    frame = luigi.Parameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()
    burst_data_csv = luigi.Parameter()
    poeorb_path = luigi.Parameter()
    resorb_path = luigi.Parameter()
    cleanup = luigi.BoolParameter()
    dem_img = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(str(self.workdir)).joinpath(
                f"{self.track}_{self.frame}_initialsetup_status_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("initial setup task", sensor=self.sensor)

        with open(self.proc_file, "r") as proc_file_obj:
            proc_config = ProcConfig.from_file(proc_file_obj)

        outdir = Path(proc_config.output_path)
        pols = list(self.polarization)

        # get the relative orbit number, which is int value of the numeric part of the track name
        rel_orbit = int(re.findall(r"\d+", str(self.track))[0])

        # get slc input information
        slc_query_results = query_slc_inputs(
            str(proc_config.database_path),
            str(self.shape_file),
            self.start_date,
            self.end_date,
            str(self.orbit),
            rel_orbit,
            pols,
            self.sensor
        )

        if slc_query_results is None:
            raise ValueError(
                f"Nothing was returned for {self.track}_{self.frame} "
                f"start_date: {self.start_date} "
                f"end_date: {self.end_date} "
                f"orbit: {self.orbit}"
            )

        # here scenes_list and download_list are overwritten for each polarization
        # IW products in conflict-free mode products VV and VH polarization over land
        slc_inputs_df = pd.concat(
            [slc_inputs(slc_query_results[pol]) for pol in pols],
            ignore_index=True
        )

        # download slc data
        download_dir = outdir / __RAW__

        os.makedirs(download_dir, exist_ok=True)

        download_list = slc_inputs_df.url.unique()
        download_tasks = []
        for slc_url in download_list:
            scene_date = Path(slc_url).name.split("_")[5].split("T")[0]
            download_tasks.append(
                SlcDataDownload(
                    slc_scene=slc_url.rstrip(),
                    polarization=self.polarization,
                    poeorb_path=self.poeorb_path,
                    resorb_path=self.resorb_path,
                    workdir=self.workdir,
                    output_dir=Path(download_dir).joinpath(scene_date),
                )
            )
        yield download_tasks

        # Detect scenes w/ incomplete/bad raw data, and remove those scenes from
        # processing while logging the situation for post-processing analysis.
        drop_whole_date_if_corrupt = True

        if drop_whole_date_if_corrupt:
            for _task in download_tasks:
                with open(_task.output().path) as fid:
                    failed_file = fid.readline().strip()
                    if not failed_file:
                        continue

                    scene_date = failed_file.split("_")[5].split("T")[0]
                    log.info(
                        f"corrupted zip file {failed_file}, removed whole date {scene_date} from processing"
                    )

                    scene_date = f"{scene_date[0:4]}-{scene_date[4:6]}-{scene_date[6:8]}"
                    indexes = slc_inputs_df[slc_inputs_df["date"].astype(str) == scene_date].index
                    slc_inputs_df.drop(indexes, inplace=True)
        else:
            for _task in download_tasks:
                with open(_task.output().path) as fid:
                    out_name = fid.readline().rstrip()
                    if re.match(SLC_PATTERN, out_name):
                        log.info(
                            f"corrupted zip file {out_name} removed from further processing"
                        )
                        indexes = slc_inputs_df[
                            slc_inputs_df["url"].map(lambda x: Path(x).name) == out_name
                        ].index
                        slc_inputs_df.drop(indexes, inplace=True)

        # save slc burst data details which is used by different tasks
        slc_inputs_df.to_csv(self.burst_data_csv)

        # Write reference scene before we start processing
        formatted_scene_dates = set([str(dt).replace("-", "") for dt in slc_inputs_df["date"]])
        ref_scene_date = calculate_primary(formatted_scene_dates)
        log.info("Automatically computed primary reference scene date", ref_scene_date=ref_scene_date)

        with open(outdir / 'lists' / 'primary_ref_scene', 'w') as ref_scene_file:
            ref_scene_file.write(ref_scene_date.strftime(__DATE_FMT__))

        # Write scenes list
        with open(outdir / 'lists' / 'scenes.list', 'w') as scenes_list_file:
            scenes_list_file.write('\n'.join(sorted(formatted_scene_dates)))

        with self.output().open("w") as out_fid:
            out_fid.write("")

        # Update .proc file "auto" reference scene
        if proc_config.ref_primary_scene.lower() == "auto":
            proc_config.ref_primary_scene = ref_scene_date.strftime(__DATE_FMT__)

            with open(self.proc_file, "w") as proc_file_obj:
                proc_config.save(proc_file_obj)

        # Write high level workflow metadata
        _, gamma_version = os.path.split(os.environ["GAMMA_INSTALL_DIR"])[-1].split("-")
        workdir = Path(self.workdir)

        metadata = {
            # General workflow parameters
            #
            # Note: This is also accessible indirectly in the log files, and
            # potentially in other plain text files - but repeated here
            # for easy access for external software so it doesn't need to
            # know the nity gritty of all our auxilliary files or logs.
            "track_frame_sensor": workdir.name,
            "original_work_dir": Path(self.outdir).as_posix(),
            "original_job_dir": workdir.parent.as_posix(),
            "shapefile": str(self.shape_file),
            "database": str(proc_config.database_path),
            "poeorb_path": str(self.poeorb_path),
            "resorb_path": str(self.resorb_path),
            "source_data_path": str(os.path.commonpath(list(download_list))),
            "dem_path": str(self.dem_img),
            "primary_ref_scene": ref_scene_date.strftime(__DATE_FMT__),
            "temporal_range": [
                self.start_date.strftime(__DATE_FMT__),
                self.end_date.strftime(__DATE_FMT__)
            ],
            "burst_data": str(self.burst_data_csv),
            "num_scene_dates": len(formatted_scene_dates),
            "polarizations": pols,

            # Software versions used for processing
            "gamma_version": gamma_version,
            "gamma_insar_version": insar.__version__,
            "gdal_version": str(osgeo.gdal.VersionInfo()),
        }

        # We write metadata to BOTH work and out dirs
        with (outdir / "metadata.json").open("w") as file:
            json.dump(metadata, file, indent=2)

        with (workdir.parent / "metadata.json").open("w") as file:
            json.dump(metadata, file, indent=2)


@requires(InitialSetup)
class CreateGammaDem(luigi.Task):
    """
    Runs create gamma dem task
    """

    dem_img = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_creategammadem_status_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("Beginning gamma DEM creation")

        gamma_dem_dir = Path(self.outdir).joinpath(__DEM_GAMMA__)
        mk_clean_dir(gamma_dem_dir)

        kwargs = {
            "gamma_dem_dir": gamma_dem_dir,
            "dem_img": self.dem_img,
            "track_frame": f"{self.track}_{self.frame}",
            "shapefile": str(self.shape_file),
        }

        create_gamma_dem(**kwargs)

        log.info("Gamma DEM creation complete")

        with self.output().open("w") as out_fid:
            out_fid.write("")


class ProcessSlc(luigi.Task):
    """
    Runs single slc processing task for a single polarisation.
    """

    scene_date = luigi.Parameter()
    raw_path = luigi.Parameter()
    polarization = luigi.Parameter()
    burst_data = luigi.Parameter()
    slc_dir = luigi.Parameter()
    workdir = luigi.Parameter()
    ref_primary_tab = luigi.Parameter(default=None)

    def output(self):
        return luigi.LocalTarget(
            Path(str(self.workdir)).joinpath(
                f"{self.scene_date}_{self.polarization}_slc_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(scene_date=self.scene_date, polarization=self.polarization)
        log.info("Beginning SLC processing")

        (Path(self.slc_dir) / str(self.scene_date)).mkdir(parents=True, exist_ok=True)

        slc_job = SlcProcess(
            str(self.raw_path),
            str(self.slc_dir),
            str(self.polarization),
            str(self.scene_date),
            str(self.burst_data),
            self.ref_primary_tab,
        )

        slc_job.main()

        log.info("SLC processing complete")

        with self.output().open("w") as f:
            f.write("")


@requires(InitialSetup)
class CreateFullSlc(luigi.Task):
    """
    Runs the create full slc tasks
    """

    proc_file = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_createfullslc_status_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("create full slc task")

        slc_dir = Path(self.outdir).joinpath(__SLC__)
        os.makedirs(slc_dir, exist_ok=True)

        slc_frames = get_scenes(self.burst_data_csv)

        # first create slc for one complete frame which will be a reference frame
        # to resize the incomplete frames.
        resize_primary_tab = None
        resize_primary_scene = None
        resize_primary_pol = None
        for _dt, status_frame, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)
            for _pol in _pols:
                if status_frame:
                    resize_task = ProcessSlc(
                        scene_date=slc_scene,
                        raw_path=Path(self.outdir).joinpath(__RAW__),
                        polarization=_pol,
                        burst_data=self.burst_data_csv,
                        slc_dir=slc_dir,
                        workdir=self.workdir,
                    )
                    yield resize_task
                    resize_primary_tab = Path(slc_dir).joinpath(
                        slc_scene, f"{slc_scene}_{_pol.upper()}_tab"
                    )
                    break
            if resize_primary_tab is not None:
                if resize_primary_tab.exists():
                    resize_primary_scene = slc_scene
                    resize_primary_pol = _pol
                    break

        # need at least one complete frame to enable further processing of the stacks
        # The frame definition were generated using all sentinel-1 acquisition dataset, thus
        # only processing a temporal subset might encounter stacks with all scene's frame
        # not forming a complete primary frame.
        # TODO: Generate a new reference frame using scene that has least number of bursts
        # (as we can't subset smaller scenes to larger)
        if resize_primary_tab is None:
            raise ValueError(
                f"Not a  single complete frames were available {self.track}_{self.frame}"
            )

        slc_tasks = []
        for _dt, status_frame, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)
            for _pol in _pols:
                if _pol not in self.polarization:
                    continue
                if slc_scene == resize_primary_scene and _pol == resize_primary_pol:
                    continue
                slc_tasks.append(
                    ProcessSlc(
                        scene_date=slc_scene,
                        raw_path=Path(self.outdir).joinpath(__RAW__),
                        polarization=_pol,
                        burst_data=self.burst_data_csv,
                        slc_dir=slc_dir,
                        workdir=self.workdir,
                        ref_primary_tab=resize_primary_tab,
                    )
                )
        yield slc_tasks

        # Remove any failed scenes from upstream processing if SLC files fail processing
        slc_inputs_df = pd.read_csv(self.burst_data_csv)
        rewrite = False
        for _slc_task in slc_tasks:
            with open(_slc_task.output().path) as fid:
                slc_date = fid.readline().rstrip()
                if re.match(r"^[0-9]{8}", slc_date):
                    slc_date = f"{slc_date[0:4]}-{slc_date[4:6]}-{slc_date[6:8]}"
                    log.info(
                        f"slc processing failed for scene for {slc_date}: removed from further processing"
                    )
                    indexes = slc_inputs_df[slc_inputs_df["date"] == slc_date].index
                    slc_inputs_df.drop(indexes, inplace=True)
                    rewrite = True

        # rewrite the burst_data_csv with removed scenes
        if rewrite:
            log.info(
                f"re-writing the burst data csv files after removing failed slc scenes"
            )
            slc_inputs_df.to_csv(self.burst_data_csv)

        with self.output().open("w") as out_fid:
            out_fid.write("")


class ProcessSlcMosaic(luigi.Task):
    """
    This task runs the final SLC mosaic step using the mean rlks/alks values for
    a single polarisation.
    """

    scene_date = luigi.Parameter()
    raw_path = luigi.Parameter()
    polarization = luigi.Parameter()
    burst_data = luigi.Parameter()
    slc_dir = luigi.Parameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()
    ref_primary_tab = luigi.Parameter(default=None)
    rlks = luigi.IntParameter()
    alks = luigi.IntParameter()

    def output(self):
        return luigi.LocalTarget(
            Path(str(self.workdir)).joinpath(
                f"{self.scene_date}_{self.polarization}_slc_subset_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(scene_date=self.scene_date, polarization=self.polarization)
        log.info("Beginning SLC mosaic")

        slc_job = SlcProcess(
            str(self.raw_path),
            str(self.slc_dir),
            str(self.polarization),
            str(self.scene_date),
            str(self.burst_data),
            self.ref_primary_tab,
        )

        slc_job.main_mosaic(int(self.rlks), int(self.alks))

        log.info("SLC mosaic complete")

        with self.output().open("w") as f:
            f.write("")


@requires(CreateFullSlc)
class CreateSlcMosaic(luigi.Task):
    """
    Runs the final mosaics for all scenes, for all polarisations.
    """

    proc_file = luigi.Parameter()
    multi_look = luigi.IntParameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_createslcmosaic_status_logs.out"
            )
        )

    def run(self):
        slc_dir = Path(self.outdir).joinpath(__SLC__)
        slc_frames = get_scenes(self.burst_data_csv)

        # Get all VV par files and compute range and azimuth looks
        slc_par_files = []
        for _dt, status_frame, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)
            for _pol in _pols:
                if _pol not in self.polarization or _pol.upper() != "VV":
                    continue
                slc_par = pjoin(
                    self.outdir,
                    __SLC__,
                    slc_scene,
                    f"{slc_scene}_{_pol.upper()}.slc.par",
                )
                if not exists(slc_par):
                    raise FileNotFoundError(f"missing {slc_par} file")
                slc_par_files.append(Path(slc_par))

        # range and azimuth looks are only computed from VV polarization
        rlks, alks, *_ = calculate_mean_look_values(
            slc_par_files,
            int(str(self.multi_look)),
        )

        # first create slc for one complete frame which will be a reference frame
        # to resize the incomplete frames.
        resize_primary_tab = None
        resize_primary_scene = None
        resize_primary_pol = None
        for _dt, status_frame, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)
            for _pol in _pols:
                if status_frame:
                    resize_task = ProcessSlcMosaic(
                        scene_date=slc_scene,
                        raw_path=Path(self.outdir).joinpath(__RAW__),
                        polarization=_pol,
                        burst_data=self.burst_data_csv,
                        slc_dir=slc_dir,
                        outdir=self.outdir,
                        workdir=self.workdir,
                        rlks=rlks,
                        alks=alks
                    )
                    yield resize_task
                    resize_primary_tab = Path(slc_dir).joinpath(
                        slc_scene, f"{slc_scene}_{_pol.upper()}_tab"
                    )
                    break
            if resize_primary_tab is not None:
                if resize_primary_tab.exists():
                    resize_primary_scene = slc_scene
                    resize_primary_pol = _pol
                    break

        # need at least one complete frame to enable further processing of the stacks
        # The frame definition were generated using all sentinel-1 acquisition dataset, thus
        # only processing a temporal subset might encounter stacks with all scene's frame
        # not forming a complete primary frame.
        # TODO implement a method to resize a stacks to new frames definition
        # TODO Generate a new reference frame using scene that has least number of missing burst
        if resize_primary_tab is None:
            raise ValueError(
                f"Not a  single complete frames were available {self.track}_{self.frame}"
            )

        slc_tasks = []
        for _dt, status_frame, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)
            for _pol in _pols:
                if _pol not in self.polarization:
                    continue
                if slc_scene == resize_primary_scene and _pol == resize_primary_pol:
                    continue
                slc_tasks.append(
                    ProcessSlcMosaic(
                        scene_date=slc_scene,
                        raw_path=Path(self.outdir).joinpath(__RAW__),
                        polarization=_pol,
                        burst_data=self.burst_data_csv,
                        slc_dir=slc_dir,
                        outdir=self.outdir,
                        workdir=self.workdir,
                        ref_primary_tab=resize_primary_tab,
                        rlks=rlks,
                        alks=alks
                    )
                )
        yield slc_tasks

        # clean up raw data directory immediately (as it's tens of GB / the sooner we delete it the better)
        raw_data_path = Path(self.outdir).joinpath(__RAW__)
        if self.cleanup and Path(raw_data_path).exists():
            shutil.rmtree(raw_data_path)

        with self.output().open("w") as out_fid:
            out_fid.write("")


class ReprocessSingleSLC(luigi.Task):
    """
    This task reprocesses a single SLC scene (including multilook) from scratch.

    This task is completely self-sufficient, it will download it's own raw data.

    This task assumes it is re-processing a partially completed job, and as such
    assumes this task would only be used if SLC processing had succeeded earlier,
    thus assumes the existence of multilook status output containing rlks/alks.
    """

    proc_file = luigi.Parameter()
    track = luigi.Parameter()
    frame = luigi.Parameter()
    polarization = luigi.Parameter()

    burst_data_csv = luigi.Parameter()

    poeorb_path = luigi.Parameter()
    resorb_path = luigi.Parameter()

    scene_date = luigi.Parameter()
    ref_primary_tab = luigi.Parameter()

    outdir = luigi.Parameter()
    workdir = luigi.Parameter()

    resume_token = luigi.Parameter()

    def output_path(self):
        return Path(
            f"{self.track}_{self.frame}_reprocess_{self.scene_date}_{self.polarization}_{self.resume_token}_status.out"
        )

    def progress_path(self):
        return Path(self.workdir) / self.output_path().with_suffix(".progress")

    def output(self):
        return luigi.LocalTarget(self.output_path())

    def progress(self):
        if not self.progress_path().exists():
            return None

        with self.progress_path().open() as file:
            return file.read().strip()

    def set_progress(self, value):
        with self.progress_path().open("w") as file:
            return file.write(value)

    def get_key_outputs(self):
        workdir = Path(self.workdir)

        # Read rlks/alks from multilook status
        mlk_status = workdir / f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        if not mlk_status.exists():
            raise ValueError(f"Failed to reprocess SLC, missing multilook status: {mlk_status}")

        rlks, alks = read_rlks_alks(mlk_status)

        pol = self.polarization.upper()

        slc_dir = Path(self.outdir).joinpath(__SLC__) / self.scene_date
        slc = slc_dir / SlcFilenames.SLC_FILENAME.value.format(self.scene_date, pol)
        slc_par = slc_dir / SlcFilenames.SLC_PAR_FILENAME.value.format(self.scene_date, pol)

        mli = slc_dir / MliFilenames.MLI_FILENAME.value.format(scene_date=self.scene_date, pol=pol, rlks=str(rlks))
        mli_par = slc_dir / MliFilenames.MLI_PAR_FILENAME.value.format(scene_date=self.scene_date, pol=pol, rlks=str(rlks))

        return [slc, slc_par, mli, mli_par]

    def run(self):
        workdir = Path(self.workdir)

        # Read rlks/alks from multilook status
        mlk_status = workdir / f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        if not mlk_status.exists():
            raise ValueError(f"Failed to reprocess SLC, missing multilook status: {mlk_status}")

        rlks, alks = read_rlks_alks(mlk_status)

        # Read scenes CSV and schedule SLC download via URLs
        if self.progress() is None:
            slc_inputs_df = pd.read_csv(self.burst_data_csv)

            download_dir = Path(str(self.outdir)).joinpath(__RAW__)
            os.makedirs(download_dir, exist_ok=True)

            download_list = slc_inputs_df.url.unique()
            download_tasks = []

            for slc_url in download_list:
                url_scene_date = Path(slc_url).name.split("_")[5].split("T")[0]

                if url_scene_date == self.scene_date:
                    download_task = SlcDataDownload(
                        slc_scene=slc_url.rstrip(),
                        polarization=self.polarization,
                        poeorb_path=self.poeorb_path,
                        resorb_path=self.resorb_path,
                        workdir=self.workdir,
                        output_dir=Path(download_dir).joinpath(url_scene_date),
                    )

                    # Force re-download, we clean raw data so the output status file is a lie...
                    if download_task.output().exists():
                        download_task.output().remove()

                    download_tasks.append(download_task)

            self.set_progress("download_tasks")
            yield download_tasks

        slc_dir = Path(self.outdir).joinpath(__SLC__)
        slc = slc_dir / self.scene_date / SlcFilenames.SLC_FILENAME.value.format(self.scene_date, self.polarization.upper())
        slc_par = slc_dir / self.scene_date / SlcFilenames.SLC_PAR_FILENAME.value.format(self.scene_date, self.polarization.upper())

        if self.progress() == "download_tasks":
            slc_task = ProcessSlc(
                scene_date=self.scene_date,
                raw_path=Path(self.outdir).joinpath(__RAW__),
                polarization=self.polarization,
                burst_data=self.burst_data_csv,
                slc_dir=slc_dir,
                workdir=self.workdir,
                ref_primary_tab=self.ref_primary_tab,
            )

            if slc_task.output().exists():
                slc_task.output().remove()

            self.set_progress("slc_task")
            yield slc_task

        if not slc.exists():
            raise ValueError(f'Critical failure reprocessing SLC, slc file not found: {slc}')

        if self.progress() == "slc_task":
            mosaic_task = ProcessSlcMosaic(
                scene_date=self.scene_date,
                raw_path=Path(self.outdir).joinpath(__RAW__),
                polarization=self.polarization,
                burst_data=self.burst_data_csv,
                slc_dir=slc_dir,
                outdir=self.outdir,
                workdir=self.workdir,
                ref_primary_tab=self.ref_primary_tab,
                rlks=rlks,
                alks=alks,
            )

            if mosaic_task.output().exists():
                mosaic_task.output().remove()

            self.set_progress("mosaic_task")
            yield mosaic_task

        if self.progress() == "mosaic_task":
            mli_task = Multilook(
                slc=slc,
                slc_par=slc_par,
                rlks=rlks,
                alks=alks,
                workdir=self.workdir,
            )

            if mli_task.output().exists():
                mli_task.output().remove()

            self.set_progress("mli_task")
            yield mli_task

        # Quick sanity check, we shouldn't get this far unless mli_task was scheduled
        if self.progress() != "mli_task":
            raise RuntimeError("Unexpected dynamic dependency error in ReprocessSingleSLC task")

        with self.output().open("w") as f:
            f.write(str(datetime.datetime.now()))


class Multilook(luigi.Task):
    """
    Produces multilooked SLC given a specified rlks/alks for multilooking
    """

    slc = luigi.Parameter()
    slc_par = luigi.Parameter()
    rlks = luigi.IntParameter()
    alks = luigi.IntParameter()
    workdir = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(str(self.workdir)).joinpath(f"{Path(str(self.slc)).stem}_ml_logs.out")
        )

    def run(self):
        multilook(
            Path(str(self.slc)),
            Path(str(self.slc_par)),
            int(str(self.rlks)),
            int(str(self.alks)),
        )

        with self.output().open("w") as f:
            f.write("")


@requires(CreateSlcMosaic)
class CreateMultilook(luigi.Task):
    """
    Runs creation of multi-look image task for all scenes, for all polariastions.
    """

    proc_file = luigi.Parameter()
    multi_look = luigi.IntParameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_createmultilook_status_logs.out"
            )
        )

    def run(self):
        # calculate the mean range and azimuth look values
        slc_dir = Path(self.outdir).joinpath(__SLC__)
        slc_frames = get_scenes(self.burst_data_csv)
        slc_par_files = []

        for _dt, status_frame, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)
            for _pol in _pols:
                if _pol not in self.polarization:
                    continue
                slc_par = pjoin(
                    self.outdir,
                    __SLC__,
                    slc_scene,
                    f"{slc_scene}_{_pol.upper()}.slc.par",
                )
                if not exists(slc_par):
                    raise FileNotFoundError(f"missing {slc_par} file")
                slc_par_files.append(Path(slc_par))

        # range and azimuth looks are only computed from VV polarization
        rlks, alks, *_ = calculate_mean_look_values(
            [_par for _par in slc_par_files if "VV" in _par.stem],
            int(str(self.multi_look)),
        )

        # multi-look jobs run
        ml_jobs = []
        for slc_par in slc_par_files:
            slc = slc_par.with_suffix("")
            ml_jobs.append(
                Multilook(
                    slc=slc, slc_par=slc_par, rlks=rlks, alks=alks, workdir=self.workdir
                )
            )

        yield ml_jobs

        with self.output().open("w") as out_fid:
            out_fid.write("rlks:\t {}\n".format(str(rlks)))
            out_fid.write("alks:\t {}".format(str(alks)))


@requires(CreateMultilook)
class CalcInitialBaseline(luigi.Task):
    """
    Runs calculation of initial baseline task
    """

    proc_file = luigi.Parameter()
    primary_scene_polarization = luigi.Parameter(default="VV")

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_calcinitialbaseline_status_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("Beginning baseline calculation")

        outdir = Path(self.outdir)

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        slc_frames = get_scenes(self.burst_data_csv)
        slc_par_files = []
        polarizations = [self.primary_scene_polarization]

        # Explicitly NOT supporting cross-polarisation IFGs, for now
        enable_cross_pol_ifgs = False

        for _dt, _, _pols in slc_frames:
            slc_scene = _dt.strftime(__DATE_FMT__)

            if self.primary_scene_polarization in _pols:
                slc_par = pjoin(
                    self.outdir,
                    __SLC__,
                    slc_scene,
                    "{}_{}.slc.par".format(slc_scene, self.primary_scene_polarization),
                )
            elif not enable_cross_pol_ifgs:
                continue
            else:
                slc_par = pjoin(
                    self.outdir,
                    __SLC__,
                    slc_scene,
                    "{}_{}.slc.par".format(slc_scene, _pols[0]),
                )
                polarizations.append(_pols[0])

            if not exists(slc_par):
                raise FileNotFoundError(f"missing {slc_par} file")

            slc_par_files.append(Path(slc_par))

        baseline = BaselineProcess(
            slc_par_files,
            list(set(polarizations)),
            primary_scene=read_primary_date(outdir),
            outdir=outdir,
        )

        # creates a ifg list based on sbas-network
        baseline.sbas_list(nmin=int(proc_config.min_connect), nmax=int(proc_config.max_connect))

        log.info("Baseline calculation complete")

        with self.output().open("w") as out_fid:
            out_fid.write("")


@requires(CreateGammaDem, CalcInitialBaseline)
class CoregisterDemPrimary(luigi.Task):
    """
    Runs co-registration of DEM and primary scene
    """

    multi_look = luigi.IntParameter()
    primary_scene_polarization = luigi.Parameter(default="VV")
    primary_scene = luigi.OptionalParameter(default=None)

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_coregisterdemprimary_status_logs.out"
            )
        )

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("Beginning DEM primary coregistration")

        outdir = Path(self.outdir)

        # Read rlks/alks from multilook status
        ml_file = f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        rlks, alks = read_rlks_alks(Path(self.workdir) / ml_file)

        primary_scene = read_primary_date(outdir)

        primary_slc = pjoin(
            outdir,
            __SLC__,
            primary_scene.strftime(__DATE_FMT__),
            "{}_{}.slc".format(
                primary_scene.strftime(__DATE_FMT__), self.primary_scene_polarization
            ),
        )

        primary_slc_par = Path(primary_slc).with_suffix(".slc.par")
        dem = (
            outdir
            .joinpath(__DEM_GAMMA__)
            .joinpath(f"{self.track}_{self.frame}.dem")
        )
        dem_par = dem.with_suffix(dem.suffix + ".par")

        dem_outdir = outdir / __DEM__
        mk_clean_dir(dem_outdir)

        coreg = CoregisterDem(
            rlks=rlks,
            alks=alks,
            shapefile=str(self.shape_file),
            dem=dem,
            slc=Path(primary_slc),
            dem_par=dem_par,
            slc_par=primary_slc_par,
            dem_outdir=dem_outdir,
            multi_look=self.multi_look,
        )

        coreg.main()

        log.info("DEM primary coregistration complete")

        with self.output().open("w") as out_fid:
            out_fid.write("")


class CoregisterSecondary(luigi.Task):
    """
    Runs the primary-secondary co-registration task, followed by backscatter.

    Optionally, just runs backscattter if provided with a coreg_offset and
    coreg_lut parameter to use.
    """

    proc_file = luigi.Parameter()
    list_idx = luigi.Parameter()
    slc_primary = luigi.Parameter()
    slc_secondary = luigi.Parameter()
    secondary_mli = luigi.Parameter()
    range_looks = luigi.IntParameter()
    azimuth_looks = luigi.IntParameter()
    ellip_pix_sigma0 = luigi.Parameter()
    dem_pix_gamma0 = luigi.Parameter()
    r_dem_primary_mli = luigi.Parameter()
    rdc_dem = luigi.Parameter()
    geo_dem_par = luigi.Parameter()
    dem_lt_fine = luigi.Parameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{Path(str(self.slc_primary)).stem}_{Path(str(self.slc_secondary)).stem}_coreg_logs.out"
            )
        )

    def get_coreg_info(self):
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        coreg = CoregisterSlc(
            proc=proc_config,
            list_idx=str(self.list_idx),
            slc_primary=Path(str(self.slc_primary)),
            slc_secondary=Path(str(self.slc_secondary)),
            secondary_mli=Path(str(self.secondary_mli)),
            range_looks=int(str(self.range_looks)),
            azimuth_looks=int(str(self.azimuth_looks)),
            ellip_pix_sigma0=Path(str(self.ellip_pix_sigma0)),
            dem_pix_gamma0=Path(str(self.dem_pix_gamma0)),
            r_dem_primary_mli=Path(str(self.r_dem_primary_mli)),
            rdc_dem=Path(str(self.rdc_dem)),
            geo_dem_par=Path(str(self.geo_dem_par)),
            dem_lt_fine=Path(str(self.dem_lt_fine)),
        )

        return (coreg.secondary_lt, coreg.secondary_off)

    def run(self):
        secondary_date, secondary_pol = Path(self.slc_secondary).stem.split('_')
        primary_date, primary_pol = Path(self.slc_primary).stem.split('_')

        # coreg between differently polarised data makes no sense
        assert(secondary_pol == primary_pol)

        log = STATUS_LOGGER.bind(
            outdir=self.outdir,
            polarization=secondary_pol,
            secondary_date=secondary_date,
            slc_secondary=self.slc_secondary,
            primary_date=primary_date,
            slc_primary=self.slc_primary
        )
        log.info("Beginning SLC coregistration")

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        failed = False

        # Run SLC coreg in an exception handler that doesn't propagate exception into Luigi
        # This is to allow processing to fail without stopping the Luigi pipeline, and thus
        # allows as many scenes as possible to fully process even if some scenes fail.
        try:
            coreg_secondary = CoregisterSlc(
                proc=proc_config,
                list_idx=str(self.list_idx),
                slc_primary=Path(str(self.slc_primary)),
                slc_secondary=Path(str(self.slc_secondary)),
                secondary_mli=Path(str(self.secondary_mli)),
                range_looks=int(str(self.range_looks)),
                azimuth_looks=int(str(self.azimuth_looks)),
                ellip_pix_sigma0=Path(str(self.ellip_pix_sigma0)),
                dem_pix_gamma0=Path(str(self.dem_pix_gamma0)),
                r_dem_primary_mli=Path(str(self.r_dem_primary_mli)),
                rdc_dem=Path(str(self.rdc_dem)),
                geo_dem_par=Path(str(self.geo_dem_par)),
                dem_lt_fine=Path(str(self.dem_lt_fine)),
            )

            # Full coregistration (currently also includes backscatter)
            coreg_secondary.main()

            log.info("SLC coregistration complete")
        except Exception as e:
            log.error("SLC coregistration failed with exception", exc_info=True)
            failed = True
        finally:
            # We flag a task as complete no matter if the scene failed or not!
            # - however we do write if the scene failed, so it can be reprocessed
            # - later automatically if need be.
            with self.output().open("w") as f:
                f.write("FAILED" if failed else "")


@requires(CoregisterDemPrimary)
class CreateCoregisterSecondaries(luigi.Task):
    """
    Runs the co-registration tasks.

    The first batch of tasks produced is the primary-secondary coregistration, followed
    up by each sub-tree of secondary-secondary coregistrations in the coregistration network.
    """

    proc_file = luigi.Parameter()
    primary_scene_polarization = luigi.Parameter(default="VV")
    primary_scene = luigi.OptionalParameter(default=None)

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_coregister_secondarys_status_logs.out"
            )
        )

    def trigger_resume(self, reprocess_dates: List[str], reprocess_failed_scenes: bool):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")

        # Remove our output to re-trigger this job, which will trigger CoregisterSecondary
        # for all dates, however only those missing outputs will run.
        output = self.output()

        if output.exists():
            output.remove()

        # Remove completion status files for any failed SLC coreg tasks
        triggered_pairs = []

        if reprocess_failed_scenes:
            for status_out in Path(self.workdir).glob("*_coreg_logs.out"):
                with status_out.open("r") as file:
                    contents = file.read().splitlines()

                if len(contents) > 0 and "FAILED" in contents[0]:
                    parts = status_out.name.split("_")
                    primary_date, secondary_date = parts[0], parts[2]

                    triggered_pairs.append((primary_date, secondary_date))

                    log.info(f"Resuming SLC coregistration ({primary_date}, {secondary_date}) because of FAILED processing")
                    status_out.unlink()

        # Remove completion status files for any we're asked to
        for date in reprocess_dates:
            for status_out in Path(self.workdir).glob(f"*_*_{date}_*_coreg_logs.out"):
                parts = status_out.name.split("_")
                primary_date, secondary_date = parts[0], parts[2]

                triggered_pairs.append((primary_date, secondary_date))

                log.info(f"Resuming SLC coregistration ({primary_date}, {secondary_date}) because of dependency")
                status_out.unlink()

        return triggered_pairs


    def get_base_kwargs(self):
        outdir = Path(self.outdir)

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        primary_scene = read_primary_date(outdir)

        # get range and azimuth looked values
        ml_file = Path(self.workdir).joinpath(
            f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        )
        rlks, alks = read_rlks_alks(ml_file)

        primary_scene = primary_scene.strftime(__DATE_FMT__)
        primary_slc_prefix = (
            f"{primary_scene}_{str(self.primary_scene_polarization).upper()}"
        )
        primary_slc_rlks_prefix = f"{primary_slc_prefix}_{rlks}rlks"
        r_dem_primary_slc_prefix = f"r{primary_slc_prefix}"

        dem_dir = outdir / __DEM__
        dem_filenames = CoregisterDem.dem_filenames(
            dem_prefix=primary_slc_rlks_prefix, outdir=dem_dir
        )
        slc_primary_dir = outdir / __SLC__ / primary_scene
        dem_primary_names = CoregisterDem.dem_primary_names(
            slc_prefix=primary_slc_rlks_prefix,
            r_slc_prefix=r_dem_primary_slc_prefix,
            outdir=slc_primary_dir,
        )
        kwargs = {
            "proc_file": self.proc_file,
            "list_idx": "-",
            "slc_primary": slc_primary_dir.joinpath(f"{primary_slc_prefix}.slc"),
            "range_looks": rlks,
            "azimuth_looks": alks,
            "ellip_pix_sigma0": dem_filenames["ellip_pix_sigma0"],
            "dem_pix_gamma0": dem_filenames["dem_pix_gam"],
            "r_dem_primary_mli": dem_primary_names["r_dem_primary_mli"],
            "rdc_dem": dem_filenames["rdc_dem"],
            "geo_dem_par": dem_filenames["geo_dem_par"],
            "dem_lt_fine": dem_filenames["dem_lt_fine"],
            "outdir": self.outdir,
            "workdir": Path(self.workdir),
        }

        return kwargs

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("co-register primary-secondaries task")

        outdir = Path(self.outdir)

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        slc_frames = get_scenes(self.burst_data_csv)

        primary_scene = read_primary_date(outdir)

        coreg_tree = create_secondary_coreg_tree(
            primary_scene, [dt for dt, _, _ in slc_frames]
        )

        primary_polarizations = [
            pols for dt, _, pols in slc_frames if dt.date() == primary_scene
        ]
        assert len(primary_polarizations) == 1

        # TODO if primary polarization data does not exist in SLC archive then
        # TODO choose other polarization or raise Error.
        if self.primary_scene_polarization not in primary_polarizations[0]:
            raise ValueError(
                f"{self.primary_scene_polarization}  not available in SLC data for {primary_scene}"
            )

        primary_pol = str(self.primary_scene_polarization).upper()

        # get range and azimuth looked values
        ml_file = Path(self.workdir).joinpath(
            f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        )
        rlks, alks = read_rlks_alks(ml_file)

        primary_scene = primary_scene.strftime(__DATE_FMT__)

        kwargs = self.get_base_kwargs()

        secondary_coreg_jobs = []

        for list_index, list_dates in enumerate(coreg_tree):
            list_index += 1  # list index is 1-based
            list_frames = [i for i in slc_frames if i[0].date() in list_dates]

            # Write list file
            list_file_path = outdir / proc_config.list_dir / f"secondaries{list_index}.list"
            if not list_file_path.parent.exists():
                list_file_path.parent.mkdir(parents=True)

            with open(list_file_path, "w") as listfile:
                list_date_strings = [
                    dt.strftime(__DATE_FMT__) for dt, _, _ in list_frames
                ]
                listfile.write("\n".join(list_date_strings))

            # Bash passes '-' for secondaries1.list, and list_index there after.
            if list_index > 1:
                kwargs["list_idx"] = list_index

            for _dt, _, _pols in list_frames:
                slc_scene = _dt.strftime(__DATE_FMT__)
                if slc_scene == primary_scene:
                    continue

                if primary_pol not in _pols:
                    log.warning(
                        f"Skipping SLC coregistration due to missing primary polarisation data for that date",
                        primary_pol=primary_pol,
                        pols=_pols,
                        slc_scene=slc_scene
                    )
                    continue

                secondary_dir = outdir / __SLC__ / slc_scene

                secondary_slc_prefix = f"{slc_scene}_{primary_pol}"
                kwargs["slc_secondary"] = secondary_dir / f"{secondary_slc_prefix}.slc"
                kwargs["secondary_mli"] = secondary_dir / f"{secondary_slc_prefix}_{rlks}rlks.mli"
                secondary_coreg_jobs.append(CoregisterSecondary(**kwargs))


        yield secondary_coreg_jobs

        with self.output().open("w") as f:
            f.write("")


class ProcessBackscatter(luigi.Task):
    """
    Produces the NBR (normalised radar backscatter) product for an SLC.
    """

    proc_file = luigi.Parameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()

    src_mli = luigi.Parameter()
    ellip_pix_sigma0 = luigi.Parameter()
    dem_pix_gamma0 = luigi.Parameter()
    dem_lt_fine = luigi.Parameter()
    geo_dem_par = luigi.Parameter()
    dst_stem = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{Path(str(self.src_mli)).stem}_nbr_logs.out"
            )
        )

    def run(self):
        slc_date, slc_pol = Path(self.src_mli).stem.split('_')

        log = STATUS_LOGGER.bind(
            slc=self.src_mli,
        )

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        failed = False

        try:
            structlog.threadlocal.clear_threadlocal()
            structlog.threadlocal.bind_threadlocal(
                task="SLC backscatter",
                slc_dir=self.outdir,
                slc_date=slc_date,
                slc_pol=slc_pol
            )

            log.info("Beginning SLC backscatter")

            generate_normalised_backscatter(
                Path(self.outdir),
                Path(self.src_mli),
                Path(self.ellip_pix_sigma0),
                Path(self.dem_pix_gamma0),
                Path(self.dem_lt_fine),
                Path(self.geo_dem_par),
                Path(self.dst_stem),
            )

            log.info("SLC backscatter complete")
        except Exception as e:
            log.error("SLC backscatter failed with exception", exc_info=True)
            failed = True
        finally:
            # We flag a task as complete no matter if the scene failed or not!
            # - however we do write if the scene failed, so it can be reprocessed
            # - later automatically if need be.
            with self.output().open("w") as f:
                f.write("FAILED" if failed else "")

            structlog.threadlocal.clear_threadlocal()


@requires(CreateCoregisterSecondaries)
class CreateCoregisteredBackscatter(luigi.Task):
    """
    Runs the backscatter tasks for all coregistered scenes.
    """

    proc_file = luigi.Parameter()
    polarization = luigi.ListParameter(default=None)

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_backscatter_status_logs.out"
            )
        )

    def get_create_coreg_task(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")

        # Note: We share identical parameters, so we just forward them a copy
        kwargs = {k:getattr(self,k) for k,_ in self.get_params()}

        return CreateCoregisterSecondaries(**kwargs)

    def trigger_resume(self, reprocess_dates: List[str], reprocess_failed_scenes: bool):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")

        # All we need to do is drop our outputs, as the backscatter
        # task can safely over-write itself...
        if self.output().exists():
            self.output().remove()

        # Remove completion status files for any failed SLC coreg tasks
        triggered_dates = []

        if reprocess_failed_scenes:
            for status_out in Path(self.workdir).glob("*_nbr_logs.out"):
                mli = status_out.name[:-13] + ".mli"
                scene_date = mli.split("_")[0].lstrip("r")

                with status_out.open("r") as file:
                    contents = file.read().splitlines()

                if len(contents) > 0 and "FAILED" in contents[0]:
                    triggered_dates.append(scene_date)

                    log.info(f"Resuming SLC backscatter ({mli}) because of FAILED processing")
                    status_out.unlink()

        # Remove completion status files for any we're asked to
        for date in reprocess_dates:
            for status_out in Path(self.workdir).glob(f"*{date}_*_nbr_logs.out"):
                mli = status_out.name[:-13] + ".mli"
                scene_date = mli.split("_")[0].lstrip("r")

                triggered_dates.append(scene_date)

                log.info(f"Resuming SLC backscatter ({mli}) because of dependency")
                status_out.unlink()

        return triggered_dates

    def get_base_kwargs(self):
        outdir = Path(self.outdir)

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        primary_scene = read_primary_date(outdir)

        # get range and azimuth looked values
        ml_file = Path(self.workdir).joinpath(
            f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        )
        rlks, alks = read_rlks_alks(ml_file)

        primary_scene = primary_scene.strftime(__DATE_FMT__)
        primary_slc_prefix = (
            f"{primary_scene}_{str(self.primary_scene_polarization).upper()}"
        )
        primary_slc_rlks_prefix = f"{primary_slc_prefix}_{rlks}rlks"

        dem_dir = outdir / __DEM__
        dem_filenames = CoregisterDem.dem_filenames(
            dem_prefix=primary_slc_rlks_prefix, outdir=dem_dir
        )

        kwargs = {
            "proc_file": self.proc_file,
            "outdir": self.outdir,
            "workdir": self.workdir,

            "ellip_pix_sigma0": dem_filenames["ellip_pix_sigma0"],
            "dem_pix_gamma0": dem_filenames["dem_pix_gam"],
            "dem_lt_fine": dem_filenames["dem_lt_fine"],
            "geo_dem_par": dem_filenames["geo_dem_par"],
        }

        return kwargs

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("backscatter task")

        outdir = Path(self.outdir)

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        # get range and azimuth looked values
        ml_file = Path(self.workdir).joinpath(
            f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        )
        rlks, alks = read_rlks_alks(ml_file)

        kwargs = self.get_base_kwargs()

        jobs = []

        # Create backscatter tasks for all coregistered scenes
        coreg_date_pairs = get_coreg_date_pairs(outdir, proc_config)

        for _, secondary_date in coreg_date_pairs:
            secondary_dir = outdir / __SLC__ / secondary_date

            # Then schedule other polarisations w/ dependency on primary pol
            for pol in list(self.polarization):
                prefix = f"{secondary_date}_{pol.upper()}"

                kwargs["src_mli"] = secondary_dir / f"r{prefix}.mli"
                # TBD: We have always written the backscatter w/ the same
                # pattern, but going forward we might want coregistered
                # backscatter to also have the 'r' prefix?  as some
                # backscatters in the future will 'not' be coregistered...
                kwargs["dst_stem"] = secondary_dir / f"{prefix}_{rlks}rlks"

                task = ProcessBackscatter(**kwargs)
                jobs.append(task)

        yield jobs

        with self.output().open("w") as f:
            f.write("")


class ProcessIFG(luigi.Task):
    """
    Runs the interferogram processing tasks for primary polarisation.
    """

    proc_file = luigi.Parameter()
    shape_file = luigi.Parameter()
    track = luigi.Parameter()
    frame = luigi.Parameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()

    primary_date = luigi.Parameter()
    secondary_date = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_ifg_{self.primary_date}-{self.secondary_date}_status_logs.out"
            )
        )

    def run(self):
        # Load the gamma proc config file
        with open(str(self.proc_file), 'r') as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        log = STATUS_LOGGER.bind(
            outdir=self.outdir,
            polarization=proc_config.polarisation,
            primary_date=self.primary_date,
            secondary_date=self.secondary_date
        )
        log.info("Beginning interferogram processing")

        # Run IFG processing in an exception handler that doesn't propagate exception into Luigi
        # This is to allow processing to fail without stopping the Luigi pipeline, and thus
        # allows as many scenes as possible to fully process even if some scenes fail.
        failed = False
        try:
            ic = IfgFileNames(proc_config, Path(self.shape_file), self.primary_date, self.secondary_date, self.outdir)
            dc = DEMFileNames(proc_config, self.outdir)
            tc = TempFileConfig(ic)

            # Run interferogram processing workflow w/ ifg width specified in r_primary_mli par file
            with open(Path(self.outdir) / ic.r_primary_mli_par, 'r') as fileobj:
                ifg_width = get_ifg_width(fileobj)

            # Make sure output IFG dir is clean/empty, in case
            # we're resuming an incomplete/partial job.
            mk_clean_dir(ic.ifg_dir)

            run_workflow(
                proc_config,
                ic,
                dc,
                tc,
                ifg_width)

            log.info("Interferogram complete")
        except Exception as e:
            log.error("Interferogram failed with exception", exc_info=True)
            failed = True
        finally:
            # We flag a task as complete no matter if the scene failed or not!
            with self.output().open("w") as f:
                f.write("FAILED" if failed else "")


@requires(CreateCoregisteredBackscatter)
class CreateProcessIFGs(luigi.Task):
    """
    Runs the interferogram processing tasks.
    """

    proc_file = luigi.Parameter()
    shape_file = luigi.Parameter()
    track = luigi.Parameter()
    frame = luigi.Parameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()

    def output(self):
        return luigi.LocalTarget(
            Path(self.workdir).joinpath(
                f"{self.track}_{self.frame}_create_ifgs_status_logs.out"
            )
        )

    def trigger_resume(self, reprocess_failed_scenes=True):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")

        # Load the gamma proc config file
        with open(str(self.proc_file), 'r') as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        # Remove our output to re-trigger this job, which will trigger ProcessIFGs
        # for all date pairs, however only those missing IFG outputs will run.
        output = self.output()

        if output.exists():
            output.remove()

        # Remove completion status files for IFGs tasks that are missing outputs
        # - this is distinct from those that raised errors explicitly, to handle
        # - cases people have manually deleted outputs (accidentally or intentionally)
        # - and cases where jobs have been terminated mid processing.
        reprocess_pairs = []

        ifgs_list = Path(self.outdir) / proc_config.list_dir / proc_config.ifg_list
        if ifgs_list.exists():
            with open(ifgs_list) as ifg_list_file:
                ifgs_list = [dates.split(",") for dates in ifg_list_file.read().splitlines()]

            for primary_date, secondary_date in ifgs_list:
                ic = IfgFileNames(proc_config, Path(self.shape_file), primary_date, secondary_date, self.outdir)

                # Check for existence of filtered coh geocode files, if neither exist we need to re-run.
                ifg_filt_coh_geo_out = ic.ifg_dir / ic.ifg_filt_coh_geocode_out
                ifg_filt_coh_geo_out_tiff = ic.ifg_dir / ic.ifg_filt_coh_geocode_out_tiff

                if not ic.ifg_filt_coh_geocode_out.exists() and not ifg_filt_coh_geo_out_tiff.exists():
                    log.info(f"Resuming IFG ({primary_date},{secondary_date}) because of missing geocode outputs")
                    reprocess_pairs.append((primary_date, secondary_date))

        # Remove completion status files for any failed SLC coreg tasks.
        # This is probably slightly redundant, but we 'do' write FAILED to status outs
        # in the error handler, thus for cases this occurs but the above logic doesn't
        # apply, we have this as well just in case.
        if reprocess_failed_scenes:
            for status_out in Path(self.workdir).glob("*_ifg_*_status_logs.out"):
                with status_out.open("r") as file:
                    contents = file.read().splitlines()

                if len(contents) > 0 and "FAILED" in contents[0]:
                    primary_date, secondary_date = re.split("[-_]", status_out.stem)[2:3]

                    log.info(f"Resuming IFG ({primary_date},{secondary_date}) because of FAILED processing")
                    reprocess_pairs.append((primary_date, secondary_date))

        reprocess_pairs = set(reprocess_pairs)

        # Any pairs that need reprocessing, we remove the status file of + clean the tree
        for primary_date, secondary_date in reprocess_pairs:
            status_file = self.workdir / f"{self.track}_{self.frame}_ifg_{primary_date}-{secondary_date}_status_logs.out"

            # Remove Luigi status file
            if status_file.exists():
                status_file.unlink()

        return reprocess_pairs

    def run(self):
        log = STATUS_LOGGER.bind(track_frame=f"{self.track}_{self.frame}")
        log.info("Process interferograms task")

        # Load the gamma proc config file
        with open(str(self.proc_file), 'r') as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        # Parse ifg_list to schedule jobs for each interferogram
        with open(Path(self.outdir) / proc_config.list_dir / proc_config.ifg_list) as ifg_list_file:
            ifgs_list = [dates.split(",") for dates in ifg_list_file.read().splitlines()]

        jobs = []
        for primary_date, secondary_date in ifgs_list:
            jobs.append(
                ProcessIFG(
                    proc_file=self.proc_file,
                    shape_file=self.shape_file,
                    track=self.track,
                    frame=self.frame,
                    outdir=self.outdir,
                    workdir=self.workdir,
                    primary_date=primary_date,
                    secondary_date=secondary_date
                )
            )

        yield jobs

        with self.output().open("w") as f:
            f.write("")


class TriggerResume(luigi.Task):
    """
    This job triggers resumption of processing for a specific track/frame/sensor/polarisation over a date range
    """

    track = luigi.Parameter()
    frame = luigi.Parameter()

    primary_scene = luigi.OptionalParameter(default=None)

    # Note: This task needs to take all the parameters the others do,
    # so we can re-create the other tasks for resuming
    proc_file = luigi.Parameter()
    shape_file = luigi.Parameter()
    burst_data_csv = luigi.Parameter()
    start_date = luigi.DateParameter()
    end_date = luigi.DateParameter()
    sensor = luigi.Parameter()
    polarization = luigi.ListParameter()
    cleanup = luigi.BoolParameter()
    outdir = luigi.Parameter()
    workdir = luigi.Parameter()
    orbit = luigi.Parameter()
    dem_img = luigi.Parameter()
    multi_look = luigi.IntParameter()
    poeorb_path = luigi.Parameter()
    resorb_path = luigi.Parameter()

    resume = luigi.BoolParameter()
    reprocess_failed = luigi.BoolParameter()
    resume_token = luigi.Parameter()

    workflow = luigi.EnumParameter(
        enum=ARDWorkflow, default=ARDWorkflow.Interferogram
    )

    def output_path(self):
        return Path(f"{self.track}_{self.frame}_resume_pipeline_{self.resume_token}_status.out")

    def output(self):
        return luigi.LocalTarget(Path(self.workdir) / self.output_path())

    def triggered_path(self):
        return Path(self.workdir) / self.output_path().with_suffix(".triggered")

    def run(self):
        log = STATUS_LOGGER.bind(outdir=self.outdir, workdir=self.workdir)

        #kwargs = {k:v for k,v in self.get_params()}

        # Remove args that are just for this task
        #for arg in ["resume", "reprocess_failed", "resume_token"]:
        #    del kwargs[arg]

        # Note: The above doesn't work, and I'm not too sure why... so we're
        # manually re-creating kwargs just like the ARD task does...
        kwargs = {
            "proc_file": self.proc_file,
            "shape_file": self.shape_file,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "sensor": self.sensor,
            "polarization": self.polarization,
            "track": self.track,
            "frame": self.frame,
            "outdir": self.outdir,
            "workdir": self.workdir,
            "orbit": self.orbit,
            "dem_img": self.dem_img,
            "poeorb_path": self.poeorb_path,
            "resorb_path": self.resorb_path,
            "multi_look": self.multi_look,
            "burst_data_csv": self.burst_data_csv,
            "cleanup": self.cleanup,
        }

        outdir = Path(self.outdir)

        # Load the gamma proc config file
        with open(str(self.proc_file), 'r') as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        backscatter_task = CreateCoregisteredBackscatter(**kwargs)
        coreg_task = backscatter_task.get_create_coreg_task()
        ifgs_task = CreateProcessIFGs(**kwargs)

        if self.workflow == ARDWorkflow.Interferogram:
            workflow_task = ifgs_task
        elif self.workflow == ARDWorkflow.Backscatter:
            workflow_task = backscatter_task
        else:
            raise Exception(f"Unsupported ARD workflow: {self.workflow}")

        # Note: the following logic does NOT detect/resume bad SLCs or DEM, it only handles
        # reprocessing of bad/missing coregs and IFGs currently.

        # Count number of completed products
        num_completed_coregs = len(list(Path(self.workdir).glob("*_coreg_logs.out")))
        num_completed_ifgs = len(list(Path(self.workdir).glob("*_ifg_*_status_logs.out")))

        log.info(
            f"TriggerResume of workflow {self.workflow} from {num_completed_coregs}x coreg and {num_completed_ifgs}x IFGs",
            num_completed_coregs=num_completed_coregs,
            num_completed_ifgs=num_completed_ifgs
        )

        # If we have no products, just resume the normal pipeline
        if num_completed_coregs == 0 and num_completed_ifgs == 0:
            log.info("No products need resuming, continuing w/ normal pipeline...")

            if coreg_task.output().exists():
                coreg_task.output().remove()

            if backscatter_task.output().exists():
                backscatter_task.output().remove()

            if ifgs_task.output().exists():
                ifgs_task.output().remove()

            self.triggered_path().touch()

        # Read rlks/alks
        ml_file = Path(self.workdir).joinpath(
            f"{self.track}_{self.frame}_createmultilook_status_logs.out"
        )

        if ml_file.exists():
            rlks, alks = read_rlks_alks(ml_file)

        # But if multilook hasn't been run, we never did IFGs/SLC coreg...
        # thus we should simply resume the normal pipeline.
        else:
            log.info("Multi-look never ran, continuing w/ normal pipeline...")
            self.triggered_path().touch()

        if not self.triggered_path().exists():
            prerequisite_tasks = []

            tfs = outdir.name
            log.info(f"Resuming {tfs}")

            # Trigger IFGs resume, this will tell us what pairs are being reprocessed
            reprocessed_ifgs = ifgs_task.trigger_resume(self.reprocess_failed)
            log.info("Re-processing IFGs", list=reprocessed_ifgs)

            # We need to verify the SLC inputs still exist for these IFGs... if not, reprocess
            reprocessed_single_slcs = []
            reprocessed_slc_coregs = []
            reprocessed_slc_backscatter = []

            if self.workflow == ARDWorkflow.Interferogram:
                for primary_date, secondary_date in reprocessed_ifgs:
                    ic = IfgFileNames(proc_config, Path(self.shape_file), primary_date, secondary_date, outdir)

                    # We re-use ifg's own input handling to detect this
                    try:
                        validate_ifg_input_files(ic)
                    except ProcessIfgException as e:
                        pol = proc_config.polarisation
                        status_out = f"{primary_date}_{pol}_{secondary_date}_{pol}_coreg_logs.out"
                        status_out = Path(self.workdir) / status_out

                        log.info("Triggering SLC reprocessing as coregistrations missing", missing=e.missing_files)

                        if status_out.exists():
                            status_out.unlink()

                        # Note: We intentionally don't clean primary/secondary SLC dirs as they
                        # contain files besides coreg we don't want to remove. SLC coreg
                        # can be safely re-run over it's existing files deterministically.

                        reprocessed_slc_coregs.append(primary_date)
                        reprocessed_slc_coregs.append(secondary_date)

                        # Add tertiary scene (if any)
                        for slc_scene in [primary_date, secondary_date]:
                            # Re-use slc coreg task for parameter acquisition
                            coreg_kwargs = coreg_task.get_base_kwargs()
                            del coreg_kwargs["proc_file"]
                            del coreg_kwargs["outdir"]
                            del coreg_kwargs["workdir"]
                            list_idx = "-"

                            for list_file_path in (outdir / proc_config.list_dir).glob("secondaries*.list"):
                                list_file_idx = int(list_file_path.stem[11:])

                                with list_file_path.open('r') as file:
                                    list_dates = file.read().splitlines()

                                if slc_scene in list_dates:
                                    if list_file_idx > 1:
                                        list_idx = list_file_idx

                                    break

                            coreg_kwargs["list_idx"] = list_idx

                            secondary_dir = outdir / __SLC__ / slc_scene
                            secondary_slc_prefix = f"{slc_scene}_{pol}"
                            coreg_kwargs["slc_secondary"] = secondary_dir / f"{secondary_slc_prefix}.slc"
                            coreg_kwargs["secondary_mli"] = secondary_dir / f"{secondary_slc_prefix}_{rlks}rlks.mli"
                            tertiary_task = CoregisterSlc(proc=proc_config, **coreg_kwargs)

                            tertiary_date = tertiary_task.get_tertiary_coreg_scene()

                            if tertiary_date:
                                reprocessed_single_slcs.append(tertiary_date)

            # Finally trigger SLC coreg & backscatter resumption
            # given the scenes from the missing IFG pairs
            triggered_slc_coregs = coreg_task.trigger_resume(reprocessed_slc_coregs, self.reprocess_failed)
            for primary_date, secondary_date in triggered_slc_coregs:
                reprocessed_slc_coregs.append(secondary_date)

                reprocessed_single_slcs.append(primary_date)
                reprocessed_single_slcs.append(secondary_date)

            triggered_slc_backscatter = backscatter_task.trigger_resume(reprocessed_slc_coregs, self.reprocess_failed)
            for scene_date in triggered_slc_backscatter:
                reprocessed_slc_backscatter.append(scene_date)

            reprocessed_slc_coregs = set(reprocessed_slc_coregs)
            reprocessed_single_slcs = set(reprocessed_single_slcs) | reprocessed_slc_coregs | set(reprocessed_single_slcs)
            reprocessed_slc_backscatter = set(reprocessed_slc_backscatter) | reprocessed_single_slcs

            if len(reprocessed_single_slcs) > 0:
                # Unfortunately if we're missing SLC coregs, we may also need to reprocess the SLC
                #
                # Note: As the ARD task really only supports all-or-nothing for SLC processing,
                # the fact we have ifgs that need reprocessing implies we got well and truly past SLC
                # processing successfully in previous run(s) as the (ifgs list / sbas baseline can't
                # exist without having completed SLC processing...
                #
                # so we literally just need to reproduce the DEM+SLC files for coreg again.

                # Compute primary scene
                primary_scene = read_primary_date(outdir)

                # Trigger SLC processing for primary scene (for primary DEM coreg)
                reprocessed_single_slcs.add(primary_scene.strftime(__DATE_FMT__))

                # Trigger SLC processing for other scenes (for SLC coreg)
                existing_single_slcs = set()

                for date in reprocessed_single_slcs:
                    slc_reprocess = ReprocessSingleSLC(
                        proc_file = self.proc_file,
                        track = self.track,
                        frame = self.frame,
                        polarization = proc_config.polarisation,
                        burst_data_csv = self.burst_data_csv,
                        poeorb_path = self.poeorb_path,
                        resorb_path = self.resorb_path,
                        scene_date = date,
                        ref_primary_tab = None,  # FIXME: GH issue #200
                        outdir = self.outdir,
                        workdir = self.workdir,
                        # This is to prevent tasks from prior resumes from clashing with
                        # future resumes.
                        resume_token = self.resume_token
                    )

                    slc_files_exist = all([i.exists() for i in slc_reprocess.get_key_outputs()])

                    if slc_files_exist:
                        log.info(
                            f"SLC for {date} already processed",
                            files=slc_reprocess.get_key_outputs()
                        )
                        existing_single_slcs.add(date)
                        continue

                    prerequisite_tasks.append(slc_reprocess)

                reprocessed_single_slcs -= existing_single_slcs

                # Trigger DEM tasks if we're re-processing SLC coreg as well
                #
                # Note: We don't add this to pre-requisite tasks, it's implied by
                # CreateCoregisterSecondaries's @requires
                dem_task = CreateGammaDem(**_forward_kwargs(CreateGammaDem, kwargs))
                coreg_dem_task = CoregisterDemPrimary(**_forward_kwargs(CoregisterDemPrimary, kwargs))

                if dem_task.output().exists():
                    dem_task.output().remove()

                if coreg_dem_task.output().exists():
                    coreg_dem_task.output().remove()

            self.triggered_path().touch()
            log.info("Re-processing singular SLCs", list=reprocessed_single_slcs)
            log.info("Re-processing SLC coregistrations", list=reprocessed_slc_coregs)
            log.info("Re-processing SLC backscatter", list=reprocessed_slc_backscatter)

            # Yield pre-requisite tasks first
            if prerequisite_tasks:
                log.info("Issuing pre-requisite reprocessing tasks")
                yield prerequisite_tasks

        if not workflow_task.output().exists():
            # and then finally resume the normal processing pipeline
            log.info("Issuing resumption of standard pipeline tasks")
            yield workflow_task

        with self.output().open("w") as f:
            f.write("")


class ARD(luigi.WrapperTask):
    """
    Runs the InSAR ARD pipeline using GAMMA software.

    -----------------------------------------------------------------------------
    minimum parameter required to run using default luigi Parameter set in luigi.cfg
    ------------------------------------------------------------------------------
    usage:{
        luigi --module process_gamma ARD
        --proc-file <path to the .proc config file>
        --shape-file <path to an ESRI shape file (.shp)>
        --start-date <start date of SLC acquisition>
        --end-date <end date of SLC acquisition>
        --workdir <base working directory where luigi logs will be stored>
        --outdir <output directory where processed data will be stored>
        --local-scheduler (use only local-scheduler)
        --workers <number of workers>
    }
    """

    # .proc config path (holds all settings except query)
    proc_file = luigi.Parameter()

    # Query params (must be provided to task)
    shape_file = luigi.Parameter()
    start_date = luigi.DateParameter()
    end_date = luigi.DateParameter()

    # Overridable query params (can come from .proc, or task)
    sensor = luigi.Parameter(default=None)
    polarization = luigi.ListParameter(default=None)
    orbit = luigi.Parameter(default=None)

    # .proc overrides
    cleanup = luigi.BoolParameter(
        default=None, significant=False, parsing=luigi.BoolParameter.EXPLICIT_PARSING
    )
    outdir = luigi.Parameter(default=None)
    workdir = luigi.Parameter(default=None)
    database_path = luigi.Parameter(default=None)
    primary_dem_image = luigi.Parameter(default=None)
    multi_look = luigi.IntParameter(default=None)
    poeorb_path = luigi.Parameter(default=None)
    resorb_path = luigi.Parameter(default=None)
    workflow = luigi.EnumParameter(
        enum=ARDWorkflow, default=None
    )

    # Job resume triggers
    resume = luigi.BoolParameter(
        default=False, parsing=luigi.BoolParameter.EXPLICIT_PARSING
    )
    reprocess_failed = luigi.BoolParameter(
        default=False, parsing=luigi.BoolParameter.EXPLICIT_PARSING
    )

    def requires(self):
        log = STATUS_LOGGER.bind(shape_file=self.shape_file)

        shape_file = Path(self.shape_file)
        pols = self.polarization

        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        orbit = str(self.orbit or proc_config.orbit)[:1].upper()

        # We currently infer track/frame from the shapefile name... this is dodgy
        pass

        # Match <track>_<frame> prefix syntax
        # Note: this doesn't match _<sensor> suffix which is unstructured
        if not re.match(__TRACK_FRAME__, shape_file.stem):
            msg = f"{shape_file.stem} should be of {__TRACK_FRAME__} format"
            log.error(msg)
            raise ValueError(msg)

        # Extract info from shapefile
        vec_file_parts = shape_file.stem.split("_")
        if len(vec_file_parts) != 3:
            msg = f"File '{shape_file}' does not match <track>_<frame>_<sensor>"
            log.error(msg)
            raise ValueError(msg)

        # Extract <track>_<frame>_<sensor> from shapefile (eg: T118D_F32S_S1A.shp)
        track, frame, shapefile_sensor = vec_file_parts

        # Ensure shapefile is for a single track/frame IF it specifies such info
        # and that it matches the specified track/frame intended for the job.
        #
        # Note: Ideally we don't get track/frame/sensor from shape file at all,
        # these should be task parameters (still need to validate shapefile against that though)
        shapefile_dbf = geopandas.GeoDataFrame.from_file(shape_file.with_suffix(".dbf"))

        if hasattr(shapefile_dbf, "frame_ID") and hasattr(shapefile_dbf, "track"):
            dbf_frames = shapefile_dbf.frame_ID.unique()
            dbf_tracks = shapefile_dbf.track.unique()

            if len(dbf_frames) != 1:
                raise Exception("Supplied shapefile contains more than one frame!")

            if len(dbf_tracks) != 1:
                raise Exception("Supplied shapefile contains more than one track!")

            if dbf_frames[0].strip().lower() != frame.lower():  # dbf has full TxxD track definition
                raise Exception("Supplied shapefile frame does not match job frame")

            if dbf_tracks[0].strip() != track[1:-1]:  # dbf only has track number
                raise Exception("Supplied shapefile track does not match job track")

        # Query SLC inputs for this location (extent specified by shape file)
        rel_orbit = int(re.findall(r"\d+", str(track))[0])
        slc_query_results = query_slc_inputs(
            proc_config.database_path,
            str(shape_file),
            self.start_date,
            self.end_date,
            orbit,
            rel_orbit,
            pols,
            self.sensor
        )

        if slc_query_results is None:
            raise ValueError(
                f"Nothing was returned for {track}_{frame} "
                f"start_date: {self.start_date} "
                f"end_date: {self.end_date} "
                f"orbit: {orbit}"
            )

        # Determine the selected sensor(s) from the query, for directory naming
        selected_sensors = set()

        for pol, dated_scenes in slc_query_results.items():
            for date, swathes in dated_scenes.items():
                for swath, scenes in swathes.items():
                    for slc_id, slc_metadata in scenes.items():
                        if "sensor" in slc_metadata:
                            selected_sensors.add(slc_metadata["sensor"])

        selected_sensors = "_".join(sorted(selected_sensors))

        # Kick off processing task in appropriate frame dirs
        tfs = f"{track}_{frame}_{selected_sensors}"

        # Override input proc settings as required...
        # - map luigi params to compatible names

        # FIXME: We probably want to not do this (forcing tfs subdirs), this is opinionated
        # and there's no clear reason for us to be opinionated here... the DB query to do
        # so definitely complicates the code (40+ lines above), unnecessarily
        #
        # Also this causes a disconnect between --outdir (base dir to put tfs dir into)
        # vs .proc OUTPUT_PATH which is the actual output path (not a base dir)
        self.output_path = (Path(self.outdir) / tfs).as_posix() if self.outdir else None
        self.job_path = (Path(self.workdir) / tfs).as_posix() if self.workdir else None

        override_params = [
            # Note: "sensor" is NOT over-written...
            # ARD sensor parameter (satellite selector, eg: S1A vs. S1B) is not
            # the same a .proc sensor (selects between constellations such as
            # Sentinel-1 vs. RADARSAT)
            # TODO: we probably want to rename these in the future... will need
            # a review w/ InSAR team on their preferred terminology soon.

            "multi_look",
            "cleanup",
            "output_path",
            "job_path",
            "database_path",
            "primary_dem_image",
            "poeorb_path",
            "resorb_path"
        ]

        for name in override_params:
            if hasattr(self, name) and getattr(self, name) is not None:
                override_value = getattr(self, name)
                log.info("Overriding .proc setting",
                    setting=name,
                    old_value=getattr(proc_config, name),
                    value=override_value
                )
                setattr(proc_config, name, override_value)

        # Explicitly handle workflow enum
        workflow = self.workflow
        if workflow:
            proc_config.workflow = str(workflow)

        else:
            matching_workflow = [name for name in ARDWorkflow if name.lower() == proc_config.workflow.lower()]
            if not matching_workflow:
                raise Exception(f"Failed to match .proc workflow {proc_config.workflow} to ARDWorkflow enum!")

            workflow = matching_workflow[0]

        if pols:
            # Note: proc_config only takes the primary polarisation
            # - this is the polarisation used for IFGs, not secondary.
            #
            # We assume first polarisation is the primary.
            proc_config.polarisation = pols[0]
        else:
            pols = [proc_config.polarisation or "VV"]

        # Infer key variables from it
        self.output_path = Path(proc_config.output_path)
        self.job_path = Path(proc_config.job_path)
        orbit = proc_config.orbit[:1].upper()
        proc_file = self.output_path / "config.proc"

        # Create dirs
        os.makedirs(self.output_path / proc_config.list_dir, exist_ok=True)
        os.makedirs(self.job_path, exist_ok=True)

        # If proc_file already exists (eg: because this is a resume), assert that
        # this job has identical settings to the last one, so we don't produce
        # inconsistent data.
        #
        # In this process we also re-inherit any auto/blank settings.
        # Note: This is only required due to the less than ideal design we
        # have where we have had to put a fair bit of logic into requires()
        # which is in fact called multiple times (even after InitialSetup!)

        if proc_file.exists():
            with proc_file.open("r") as proc_fileobj:
                existing_config = ProcConfig.from_file(proc_fileobj)

            assert(existing_config.__slots__ == proc_config.__slots__)

            conflicts = []
            for name in proc_config.__slots__:
                # special case for cleanup, which we allow to change
                if name == "cleanup":
                    continue

                new_val = getattr(proc_config, name)
                old_val = getattr(existing_config, name)

                # If there's no such new value or it's "auto", inherit old.
                no_new_val = new_val is None or not str(new_val)
                if no_new_val or str(new_val) == "auto":
                    setattr(proc_config, name, old_val)

                # Otherwise, ensure values match / haven't changed.
                elif str(new_val) != str(old_val):
                    conflicts.append((name, new_val, old_val))

            if conflicts:
                msg = f"New .proc settings do not match existing {proc_file}"
                error = Exception(msg)
                error.state = { "conflicts": conflicts }
                log.info(msg, **error.state)
                raise error

        # Finally save final config and
        with open(proc_file, "w") as proc_fileobj:
            proc_config.save(proc_fileobj)

        # generate (just once) a unique token for tasks that need to re-run
        if self.resume:
            if not hasattr(self, 'resume_token'):
                self.resume_token = datetime.datetime.now().strftime("%Y%m%d-%H%M")

        # Coregistration processing
        ard_tasks = []
        self.output_dirs = [self.output_path]

        kwargs = {
            "proc_file": proc_file,
            "shape_file": shape_file,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "sensor": self.sensor,
            "polarization": pols,
            "track": track,
            "frame": frame,
            "outdir": self.output_path,
            "workdir": self.job_path,
            "orbit": orbit,
            "dem_img": proc_config.primary_dem_image,
            "poeorb_path": proc_config.poeorb_path,
            "resorb_path": proc_config.resorb_path,
            "multi_look": int(proc_config.multi_look),
            "burst_data_csv": self.output_path / f"{track}_{frame}_burst_data.csv",
            "cleanup": bool(proc_config.cleanup),
        }

        # Yield appropriate workflow
        if self.resume:
            ard_tasks.append(TriggerResume(resume_token=self.resume_token, workflow=workflow, **kwargs))
        elif workflow == ARDWorkflow.Backscatter:
            ard_tasks.append(CreateCoregisteredBackscatter(**kwargs))
        elif workflow == ARDWorkflow.Interferogram:
            ard_tasks.append(CreateProcessIFGs(**kwargs))
        else:
            raise Exception(f'Unsupported workflow provided: {workflow}')

        yield ard_tasks

    def run(self):
        log = STATUS_LOGGER

        # Load final .proc config
        proc_file = self.output_path / "config.proc"
        with open(proc_file, "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        # Finally once all ARD pipeline dependencies are complete (eg: data processing is complete)
        # - we cleanup files that are no longer required as outputs.
        if not proc_config.cleanup:
            log.info("Cleanup of unused files skipped, all files being kept")
            return

        log.info("Cleaning up unused files")

        required_files = [
            # IFG files
            "INT/**/*_geo_unw.tif",
            "INT/**/*_flat_geo_coh.tif",
            "INT/**/*_flat_geo_int.tif",
            "INT/**/*_filt_geo_coh.tif",
            "INT/**/*_filt_geo_int.tif",
            "INT/**/*_base.par",
            "INT/**/*_bperp.par",
            "INT/**/*_geo_unw*.png",
            "INT/**/*_flat_geo_int.png",
            "INT/**/*_flat_int",

            # SLC files
            "SLC/**/r*rlks.mli",
            "SLC/**/r*rlks.mli.par",
            "SLC/**/r*.slc.par",
            "SLC/**/*sigma0.tif",
            "SLC/**/*gamma0.tif",
            "SLC/**/ACCURACY_WARNING",

            # DEM files
            "DEM/**/*rlks_geo_to_rdc.lt",
            "DEM/**/*_geo_dem.tif",
            "DEM/**/*_geo.dem.par",
            "DEM/**/diff_*rlks.par",
            "DEM/**/*_geo_lv_phi.tif",
            "DEM/**/*_geo_lv_theta.tif",
            "DEM/**/*_rdc.dem",
            "DEM/**/*lsmap*",

            # Keep all lists, metadata, and top level files
            "lists/*",
            "**/metadata*.json",
            "*"
        ]

        # Generate a list of required files we want to keep
        keep_files = []

        for outdir in self.output_dirs:
            for pattern in required_files:
                keep_files += outdir.glob(pattern)

        # Iterate every single output dir, and remove any file that's not required
        for outdir in self.output_dirs:
            for file in outdir.rglob("*"):
                if file.is_dir():
                    continue

                is_required = any([file.samefile(i) for i in keep_files])

                if not is_required:
                    log.info("Cleaning up file", file=file)
                    file.unlink()
                else:
                    log.info("Keeping required file", file=file)


def run():
    # Configure logging from built-in script logging config file
    logging_conf = pkg_resources.resource_filename("insar", "logging.cfg")
    logging.config.fileConfig(logging_conf)

    with open("insar-log.jsonl", "a") as fobj:
        structlog.configure(logger_factory=structlog.PrintLoggerFactory(fobj))

        try:
            luigi.run()
        except:
            STATUS_LOGGER.error("Unhandled exception running ARD workflow", exc_info=True)

        try:
            luigi.run()
        except Exception as e:
            state = e.state if hasattr(e, "state") else {}
            STATUS_LOGGER.error("Unhandled exception running ARD workflow", exc_info=True, **state)


if __name__ == "__name__":
    run()
