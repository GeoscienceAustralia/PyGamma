#!/usr/bin/env python

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Union, Dict

import geopandas as gpd
import pandas as pd
import shapely.wkt
from spatialist import Vector

from insar.s1_slc_metadata import Archive

_LOG = logging.getLogger(__name__)


def _check_frame_bursts(master_df: gpd.GeoDataFrame, input_data: Dict) -> Dict:
    """Check missing master SLC bursts.

    Compares input data and master bursts to determine bursts overlaps
    and inserts a missing burst information into the input_data.

    :param master_df:
        A geopandas dataframe with master SLC informations.
    :param input_data:
        An input slc data with burst informations needed to form a full frame.

    :returns:
        Input data with addition of missing master bursts number.
    """

    for dt_key, dt_val in input_data.items():
        for swath, swath_val in dt_val.items():
            master_swath_subset = master_df[master_df.swath == swath]

            swath_centroids = [
                geom.centroid
                for _id in swath_val
                for geom in swath_val[_id]["burst_extent"]
            ]

            # check if master bursts contains the centroids to determine missing bursts
            contained_bursts = []
            for idx, row in master_swath_subset.iterrows():
                for centroid in swath_centroids:
                    if row.geometry.contains(centroid):
                        contained_bursts.append(row.burst_num)

            # insert the missing bursts information into input_data
            input_data[dt_key][swath]["missing_master_bursts"] = set(
                master_swath_subset.burst_num.values
            ) - set(contained_bursts)

    return input_data


def _check_slc_input_data(
    results_df: pd.DataFrame,
    master_df: gpd.GeoDataFrame,
    rel_orbit: int,
    polarization: str,
) -> Dict:
    """
    Checks if input (results_df) has required data to form a full SLC.

    This method checks if scenes are able to a form full slc and returns the
    parameters needed for only scenes that are able to form full slc. This
    method will only log information of scenes that cannot form full SLC
    and not raise error. Implementation needs to be changed, if failed scenes
    need to be handled separately.

    :param results_df:
        An input dataframe with queried attribute results from SLC input database.
    :param master_df:
        Attributes of a vector file (frame) used in querying SLC database.
    :param rel_orbits:
        Sentinel-1 relative orbit used in vector file framing.
    :param polarization:
        A polarization subset the data while checking full frame.

    :returns:
        A dict with information of slc scenes to form full SLC.
    """

    # perform check to assert returned queried results are for rel orbits
    assert results_df.orbitNumber_rel.unique()[0] == rel_orbit

    # subset data frame for a specific polarization
    pol_subset_df = results_df[results_df.polarization == polarization]

    # create unique date scenes list file
    unique_dates = [
        dt
        for dt in pol_subset_df.acquisition_start_time.map(pd.Timestamp.date).unique()
    ]
    data_dict = dict()

    # package input data into a dict according to a unique dates in a swath
    for dt in unique_dates:
        try:
            pol_dt_subset_df = pol_subset_df[
                pol_subset_df.acquisition_start_time.map(pd.Timestamp.date) == dt
            ]
            swaths = pol_dt_subset_df.swath.unique()

            # check that all three swaths present for a given date
            assert len(swaths) == 3

            swath_dict = dict()
            for swath in swaths:
                swath_df = pol_dt_subset_df[pol_dt_subset_df.swath == swath]

                # check swath bursts are only composed from one sensor for unique date
                sensor = list(set(swath_df.sensor.values))
                assert len(sensor) == 1

                slc_ids = swath_df.id.unique()
                slc_dict = dict()
                for _id in slc_ids:
                    slc_df = swath_df[swath_df.id == _id]
                    slc_gpd = gpd.GeoDataFrame(
                        slc_df,
                        crs={"init": "epsg:4326"},
                        geometry=slc_df["AsText(bursts_metadata.burst_extent)"].map(
                            shapely.wkt.loads
                        ),
                    )
                    slc_dict[_id] = {
                        "burst_number": list(slc_gpd.burst_number.values),
                        "burst_extent": list(slc_gpd.geometry.values),
                        "sensor": sensor[0],
                        "acquisition_datetime": slc_df.acquisition_start_time.unique()[
                            0
                        ],
                        "polarization": polarization,
                        "url": slc_gpd.url.unique()[0],
                        "total_bursts": slc_gpd.total_bursts.unique()[0],
                    }
                swath_dict[swath] = slc_dict
            data_dict[dt] = swath_dict

        except AssertionError as err:
            # only log the information for scenes not available to form compute frame.
            _LOG.info("slc scene date {}: {}".format(dt.strftime("%Y-%m-%d"), err))

    return _check_frame_bursts(master_df, data_dict)


def query_slc_inputs(
    dbfile: Union[Path, str],
    spatial_subset: Union[Path, str],
    start_date: datetime,
    end_date: datetime,
    orbit: str,
    track: int,
    polarization: List[str],
) -> Dict:
    """A method to query sqlite database and generate slc input dict.

    :param dbfile:
        A full path to a sqlite database with SLC metadata including burst
        informations needed to process SLC.
    :param spatial_subset:
        A full path to frame (vector shape file) spatial extent.
    :param start_date:
        A start date to begin database query of SLC acquisition.
    :param end_date:
        An end date to stop database query of SLC acquisition.
    :param orbit:
        Sentinel-1 acquisition orbit type (A: Ascending, D: Descending).
    :param track:
        Sentinel-1 relative orbit number (track).
    :param polarization:
        List of polarization to query SLC data for.

    :return:
        Returns slc input field values for all unique date queried
        from a dbfile between start_date and end_date (inclusive of the end dates)
        for area within a spatial_subset if data is in the database. Else returns
        None.
    """
    with Archive(dbfile) as archive:
        tables_join_string = (
            "{0} INNER JOIN {1} on {0}.swath_name = {1}.swath_name INNER JOIN {2} "
            "on {2}.id = {1}.id".format(
                archive.bursts_table_name,
                archive.swath_table_name,
                archive.slc_table_name,
            )
        )
        min_date_arg = '{}.acquisition_start_time>=Datetime("{}")'.format(
            archive.slc_table_name, start_date
        )
        max_date_arg = '{}.acquisition_start_time<=Datetime("{}")'.format(
            archive.slc_table_name, end_date
        )

        columns = [
            "{}.burst_number".format(archive.bursts_table_name),
            "{}.total_bursts".format(archive.swath_table_name),
            "{}.burst_extent".format(archive.bursts_table_name),
            "{}.swath_name".format(archive.swath_table_name),
            "{}.id".format(archive.swath_table_name),
            "{}.swath".format(archive.bursts_table_name),
            "{}.orbit".format(archive.slc_table_name),
            "{}.orbitNumber_rel".format(archive.slc_table_name),
            "{}.sensor".format(archive.slc_table_name),
            "{}.polarization".format(archive.bursts_table_name),
            "{}.acquisition_start_time".format(archive.slc_table_name),
            "{}.url".format(archive.slc_table_name),
        ]

        slc_df = archive.select(
            tables_join_string=tables_join_string,
            orbit=orbit,
            track=track,
            spatial_subset=Vector(spatial_subset),
            columns=columns,
            min_date_arg=min_date_arg,
            max_date_arg=max_date_arg,
        )
        if slc_df is None:
            return

        try:
            slc_df["acquisition_start_time"] = pd.to_datetime(
                slc_df["acquisition_start_time"]
            )

            #  check queried results against master dataframe to form slc inputs
            return {
                pol: _check_slc_input_data(
                    slc_df, gpd.read_file(spatial_subset), track, pol
                )
                for pol in polarization
            }

        except (AttributeError, AssertionError, TypeError) as err:
            raise err


def _write_list(data: List, fid: Union[Path, str]) -> None:
    """Helper method to write files."""

    with open(Path(fid.as_posix()), "w") as out_fid:
        for line in data:
            out_fid.write(line + "\n")


def slc_inputs(slc_data_input: Dict) -> pd.DataFrame:
    """
    Subsets SLC query results to a required parameters for SLC processing using GAMMA SOFTWARE.

    :param slc_data_input:
        SLC input data that were queried from the database.

    :returns:
        A dataframe with sub-set of queried attributes needed to form SLC.
    """

    _regx_uuid = r"[0-9a-fA-F]{8}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{12}"
    _swath_keys = ["IW1", "IW2", "IW3"]
    _missing_master_bursts_key = "missing_master_bursts"

    def _get_scene_data(scene_dt):
        return slc_data_input[scene_dt]

    def _get_swath_data(scene_dt, swath):
        return slc_data_input[scene_dt][swath]

    def _get_id_data(scene_dt, swath, _id):
        return slc_data_input[scene_dt][swath][_id]

    scene_dates = sorted([dt for dt in slc_data_input])

    # create dataframe and store slc details
    slc_input_df = pd.DataFrame()

    for dt in scene_dates:
        for swath in _swath_keys:
            missing_master_bursts = list(
                _get_id_data(dt, swath, _missing_master_bursts_key)
            )
            for slc_id, slc_val in _get_swath_data(dt, swath).items():
                if re.match(_regx_uuid, slc_id):
                    slc_input_df = slc_input_df.append(
                        {
                            "date": dt,
                            "swath": swath,
                            "burst_number": slc_val["burst_number"],
                            "sensor": slc_val["sensor"],
                            "url": slc_val["url"],
                            "total_bursts": slc_val["total_bursts"],
                            "polarization": slc_val["polarization"],
                            "acquistion_datetime": slc_val["acquisition_datetime"],
                            "missing_master_bursts": list(map(lambda x: int(x), missing_master_bursts))
                        },
                        ignore_index=True,
                    )
    return slc_input_df
