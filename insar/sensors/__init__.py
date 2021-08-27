from insar.sensors.data import identify_data_source, get_data_swath_info, acquire_source_data
from . import s1
from . import rsat2

# Identifiers returned from identify_data_source
S1_ID = s1.METADATA.constellation_name
RSAT2_ID = rsat2.METADATA.constellation_name

__all__ = ["identify_data_source", "get_data_swath_info", "acquire_source_data", "S1_ID", "RSAT2_ID"]
