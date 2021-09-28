import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import s1
from . import rsat2
from . import palsar

from insar.constant import SCENE_DATE_FMT

_sensors = {
    s1.METADATA.constellation_name: s1,
    rsat2.METADATA.constellation_name: rsat2,
    palsar.METADATA.constellation_name: palsar,
}

def identify_data_source(name: str):
    """
    Identify the constellation/satellite name a source data path is for.

    :param name:
        The source data path name to be identified.
    :returns:
        A tuple of (constellation, satellite) names identified.
    """
    # Note: In the future we may want to return a product type as well...
    # (eg: Level 0/1 products we may be interested in, like SLC and GRD)

    # Turn absolute paths into just the filenames
    name = Path(name).name

    # Check Sentinel-1
    s1_match = re.match(s1.SOURCE_DATA_PATTERN, name)
    if s1_match:
        scene_date = datetime.strptime(s1_match.group("start"), "%Y%m%dT%H%M%S")
        return s1.METADATA.constellation_name, s1_match.group("sensor"), scene_date.strftime(SCENE_DATE_FMT)

    # Check RADARSAT-2
    rsat2_match = re.match(rsat2.SOURCE_DATA_PATTERN, name)
    if rsat2_match:
        # There is only a single satellite in RSAT2 constellation,
        # so it has a hard-coded sensor name.
        scene_date = rsat2_match.group("start_date")
        return rsat2.METADATA.constellation_name, rsat2.METADATA.constellation_members[0], scene_date

    # Check ALOS PALSAR
    palsar_match = re.match(palsar.SOURCE_DATA_PATTERN, name)
    if palsar_match:
        scene_date = palsar_match.group("product_date")
        return palsar.METADATA.constellation_name, palsar_match.group("sensor_id"), scene_date

    raise Exception(f"Unrecognised data source file: {name}")

def _dispatch(constellation_or_pathname: str):
    if constellation_or_pathname in _sensors:
        return _sensors[constellation_or_pathname]

    id_constellation, _, _ = identify_data_source(constellation_or_pathname)
    if id_constellation not in _sensors:
        raise RuntimeError("Unsupported data source: " + constellation_or_pathname)

    return _sensors[id_constellation]


def get_data_swath_info(
    source_data: str,
    raw_data_path: Optional[Path] = None
):
    """
    Extract information for each (sub)swath in a data product.

    Each (sub)swath information dict has the following entries:
     * `date`: The date assigned to the (sub)swath.
     * `swath_extent`: The geospatial extent ((minx, miny), (maxx, maxy)) of the (sub)swath.
     * `sensor`: The sensor that acquired this (sub)swath.
     * `url`: The original URL of the source data containing this (sub)swath
     * `polarization`: The polarisation of the (sub)swath
     * `acquisition_datetime`: The UTC timestamp the (sub)swath acquisition by the satellite STARTED
     * `swath`: A swath index IF the data source contains many consecutive (sub)swaths.
     * `burst_number`: What burst indices are contained within this swath (if any)
     * `total_bursts`: Total number of bursts in this swath (if any)
     * `missing_primary_bursts`: What burst indices are missing from this swath (if any)

    Note: Some satellites break (sub)swaths into finer elements, which we call
    bursts (following ESA terminology for S1).  For satellites which do NOT do
    this refinement, burst-related information values are ignored.

    :param source_data:
        The source data path name to be identified.
    :returns:
        A list of dictionary objects representing swaths (or subswaths) in the data product.
    """

    try:
        local_path = Path(source_data)

        return _dispatch(local_path.name).get_data_swath_info(local_path, raw_data_path)
    except Exception as e:
        raise RuntimeError("Unsupported path!\n" + str(e))


# Note: source_path is explicitly a str... it's possible we may need
# to support non-local-file paths in the future (eg: S3 buckets or NCI MDSS paths)
def acquire_source_data(
    source_path: str,
    dst_dir: Path,
    pols: Optional[List[str]] = None,
    **kwargs
):
    """
    Acquires the data products for processing from a source data product.

    An example of a source data product is S1 .SAFE or RS2 multi-file structures.

    This function simply lets us treat source data as a path, from which we can
    simply extract data for polarisations we are interested in processing.

    :param source_path:
        The source data path to extract polarised data from.
    :param dst_dir:
        The directory to extract the acquired data into.
    :param pols:
        An optional list of polarisations we are interested in acquiring data for,
        if not provided all possible to be processed will be acquired.
    """
    try:
        local_path = Path(source_path)

        return _dispatch(local_path.name).acquire_source_data(source_path, dst_dir, pols, **kwargs)
    except Exception as e:
        raise RuntimeError("Unsupported path!\n" + str(e))
