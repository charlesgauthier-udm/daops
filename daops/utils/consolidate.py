import collections
import glob
import os
import re

import xarray as xr
from roocs_utils.exceptions import InvalidCollection
from roocs_utils.project_utils import derive_ds_id
from roocs_utils.project_utils import dset_to_filepaths
from roocs_utils.project_utils import get_project_base_dir
from roocs_utils.project_utils import get_project_name
from roocs_utils.utils.file_utils import FileMapper
from roocs_utils.xarray_utils.xarray_utils import open_xr_dataset

from daops import logging
from daops.catalog import get_catalog
from daops.utils.core import _wrap_sequence

LOGGER = logging.getLogger(__file__)


def to_year(time_string):
    "Returns the year in a time string as an integer."
    return int(time_string.split("-")[0])


def get_year(dct, key, default):
    """Gets a year from a datetime string in a dictionary.
    Defaults to the value of `default` if not found."""
    return to_year(dct.get(key, str(default)))


def get_years_from_file(fpath):
    """Attempts to extract years from a file.
    First by examining the file name. If that doesn't work then it
    reads the file contents and looks at the time axis.

    Returns a set of years.
    """
    # Try to use filename
    time_comps = os.path.splitext(os.path.basename(fpath))[0].split("_")[-1].split("-")
    years = {int(tm[:4]) for tm in time_comps if re.match(r"^\d{4,}", tm)}

    # If a range of years 
    if len(years) > 1:
        years = set(range(min(years), max(years) + 1))

    # If no years, try reading the file
    if not years:
        ds = open_xr_dataset(fpath)
        if hasattr(ds, "time"):
            years = {int(yr) for yr in ds.time.dt.year}

    return years


def get_files_matching_time_range(time_param, file_paths):
    """
    Using the settings in `time_param`, examine each file to see if it contains
    years that are in the requested range.

    The `time_param` can have three types: 
        1. type: "interval":
           - defined with "start_time" and "end_time"
        2. type: "series":
           - defined with a list of "time_values"
        3. type: "none":
           - undefined

    It attempts to filter out files that do not match the selected year.
    For any file that we cannot do this with, the file will be read by
    xarray.

    Args:
        time_param (TimeParameter): time parameter of requested date/times
        file_paths (list): list of file paths
    Returns:
        file_paths (list): filtered list of file paths
    """
    # Return all file paths if no time inputs specified
    if time_param.type == "none":
        return file_paths

    LOGGER.info(f"Testing {len(file_paths)} files in time range: ...")
    files_in_time_range = []

    # Handle times differently depending on the type of time parameter
    time_dict = kwargs["time"].asdict()

    if time_param.type == "interval":

        req_start_year = get_year(time_dict, "start_time", -99999999)
        req_end_year = get_year(time_dict, "end_time", 999999999)

        # Get first and last years in files
        first_year = min(get_years_from_file(file_paths[0]))
        last_year = min(get_years_from_file(file_paths[-1]))

        # Work through the list of file paths checking if each matches
        for fpath in file_paths:
            years = get_years_from_file(fpath)
            match = [year for year in years if year >= req_start_year \
                     and year <= req_end_year]
            if match:
                files_in_time_range.append(fpath)

    elif time_param.type == "series":

        # Get requested years and match to files whose years intersect
        req_years = {to_year(tm) for tm in time_dict.get("time_values", [])}

        for fpath in file_paths:
            years = get_years_from_file(fpath)
            if req_years.intersection(years):
                files_in_time_range.append(fpath)

    # If no files are matched then raise an exception
    if len(files_in_time_range) == 0:
        raise Exception(
            f"No files found in given time range for {dset}"
        )

    LOGGER.info(f"Kept {len(files_in_time_range)} files")
    return files_in_time_range


def consolidate(collection, **kwargs):
    """
    Finds the file paths relating to each input dataset. If a time range has been supplied then only the files
    relating to this time range are recorded.

    :param collection: (roocs_utils.CollectionParameter) The collection of datasets to process.
    :param kwargs: Arguments of the operation taking place e.g. subset, average, or re-grid.
    :return: An ordered dictionary of each dataset from the collection argument and the file paths
             relating to it.
    """
    catalog = None
    time = None

    collection = _wrap_sequence(collection.tuple)

    if not isinstance(collection[0], FileMapper):
        project = get_project_name(collection[0])
        catalog = get_catalog(project)

    filtered_refs = collections.OrderedDict()

    time_param = kwargs.get("time")

    for dset in collection:

        if not catalog:
            file_paths = dset_to_filepaths(dset, force=True)

            if time_param:
                file_paths = get_files_matching_time_range(time_param, file_paths)

            filtered_refs[dset] = file_paths

        else:
            ds_id = derive_ds_id(dset)
            result = catalog.search(collection=ds_id, time=time)

            if len(result) == 0:
                result = catalog.search(collection=ds_id, time=None)
                if len(result) > 0:
                    raise Exception(f"No files found in given time range for {dset}")
                else:
                    raise InvalidCollection(
                        f"{dset} is not in the list of available data."
                    )

            LOGGER.info(f"Found {len(result)} files")

            filtered_refs = result.files()

    return filtered_refs
