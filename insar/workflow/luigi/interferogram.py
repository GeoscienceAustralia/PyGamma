import luigi.configuration
import luigi
import json
import re

from pathlib import Path
from typing import Tuple, List, Generator

from luigi.util import requires

from insar.process_ifg import run_workflow, get_ifg_width, TempFilePaths
from insar.project import ProcConfig, is_flag_value_enabled
from insar.paths.interferogram import InterferogramPaths
from insar.paths.stack import StackPaths
from insar.paths.dem import DEMPaths
from insar.coreg_utils import read_land_center_coords
from insar.stack import load_stack_ifg_pairs
from insar.logs import STATUS_LOGGER as LOG
from insar.workflow.luigi.utils import tdir, mk_clean_dir, PathParameter
from insar.workflow.luigi.backscatter import CreateCoregisteredBackscatter


class ProcessIFG(luigi.Task):
    """
    Runs the interferogram processing tasks for primary polarisation.
    """

    proc_file = PathParameter()
    shape_file = PathParameter()
    stack_id = luigi.Parameter()
    outdir = PathParameter()
    workdir = PathParameter()

    primary_date = luigi.Parameter()
    secondary_date = luigi.Parameter()

    def output(self) -> luigi.LocalTarget:
        return luigi.LocalTarget(
            tdir(self.workdir) / f"{self.stack_id}_ifg_{self.primary_date}-{self.secondary_date}_status_logs.out"
        )

    def run(self) -> None:
        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        log = LOG.bind(
            outdir=self.outdir,
            polarisation=proc_config.polarisation,
            primary_date=self.primary_date,
            secondary_date=self.secondary_date,
        )
        log.info(f"Beginning interferogram processing for {self.primary_date} - {self.secondary_date}")

        # Run IFG processing in an exception handler that doesn't propagate exception into Luigi
        # This is to allow processing to fail without stopping the Luigi pipeline, and thus
        # allows as many scenes as possible to fully process even if some scenes fail.
        failed = False
        # try:
        if True:
            ic = InterferogramPaths(proc_config, self.primary_date, self.secondary_date)
            dc = DEMPaths(proc_config)
            tc = TempFilePaths(ic)

            # Run interferogram processing workflow w/ ifg width specified in r_primary_mli par file
            with ic.r_primary_mli_par.open("r") as fileobj:
                ifg_width = get_ifg_width(fileobj)

            # Read land center coordinates from shape file (if it exists)
            land_center_latlon = None
            if proc_config.land_center:
                land_center_latlon = proc_config.land_center
            elif self.shape_file:
                land_center_latlon = read_land_center_coords(Path(self.shape_file))

            # Determine date pair orbit attributes
            # Note: This only works for S1 (but also... S1 is the only sensor we support whose data comes w/ orbit files)
            # - other sensors we ignore entirely (and thus do no baseline refinement unless forced ON), which is the safest
            # - option (and why this was the only hard-coded option before now, and remains the default).
            first_slc_meta = ic.primary_dir / f"metadata_{proc_config.polarisation}.json"
            second_slc_meta = ic.secondary_dir / f"metadata_{proc_config.polarisation}.json"

            first_orbit_precise = None
            second_orbit_precise = None

            # As noted above, only sensors which have orbit files will have this metadata
            # (which is just S1 for now)
            if first_slc_meta.exists():
                first_slc_meta_json = json.loads(first_slc_meta.read_text())

                # And some sensors may have metadata, but simply no orbit files
                if "slc" in str(first_slc_meta) and ("orbit_url" in str(first_slc_meta_json["slc"])):
                    first_orbit_precise = "POEORB" in str(first_slc_meta_json["slc"]["orbit_url"] or "")

            if second_slc_meta.exists():
                second_slc_meta_json = json.loads(second_slc_meta.read_text())

                if "slc" in str(second_slc_meta) and "orbit_url" in str(second_slc_meta_json["slc"]):
                    second_orbit_precise = "POEORB" in str(second_slc_meta_json["slc"]["orbit_url"] or "")

            # Determine if baseline refinement should be enabled based on a .proc
            # setting (this exists as InSAR team aren't sure on their exact requirements
            # right now / there's no obvious "general" solution for all cases)
            enable_refinement = False

            try:
                enable_refinement = is_flag_value_enabled(proc_config.ifg_baseline_refinement)

            except ValueError:
                if first_orbit_precise is not None and second_orbit_precise is not None:
                    if proc_config.ifg_baseline_refinement.upper() == "IF_ANY_NOT_PRECISE":
                        enable_refinement = not first_orbit_precise or not second_orbit_precise

                    elif proc_config.ifg_baseline_refinement.upper() == "IF_BOTH_NOT_PRECISE":
                        enable_refinement = not first_orbit_precise and not second_orbit_precise

                    elif proc_config.ifg_baseline_refinement.upper() == "IF_FIRST_NOT_PRECISE":
                        enable_refinement = not first_orbit_precise

                    elif proc_config.ifg_baseline_refinement.upper() == "IF_SECOND_NOT_PRECISE":
                        enable_refinement = not second_orbit_precise

            if enable_refinement:
                log.info("IFG baseline refinement enabled", ifg_baseline_refinement=proc_config.ifg_baseline_refinement)

            # Make sure output IFG dir is clean/empty, in case
            # we're resuming an incomplete/partial job.
            mk_clean_dir(ic.ifg_dir)

            run_workflow(
                proc_config,
                ic,
                dc,
                tc,
                ifg_width,
                enable_refinement=enable_refinement,
                land_center_latlon=land_center_latlon,
            )

            log.info("Interferogram complete")
            # except Exception as e:
            #    log.error("Interferogram failed with exception", exc_info=True)
            #    failed = True
            # finally:
            # We flag a task as complete no matter if the scene failed or not!
            with self.output().open("w") as f:
                f.write("FAILED" if failed else "")


@requires(CreateCoregisteredBackscatter)
class CreateProcessIFGs(luigi.Task):
    """
    Runs the interferogram processing tasks.
    """

    proc_file = PathParameter()
    shape_file = PathParameter()
    stack_id = luigi.Parameter()
    outdir = PathParameter()
    workdir = PathParameter()

    def output(self) -> luigi.LocalTarget:
        return luigi.LocalTarget(tdir(self.workdir) / f"{self.stack_id}_create_ifgs_status_logs.out")

    def trigger_resume(self, reprocess_failed_scenes: bool = True) -> List[Tuple[Path, Path]]:
        log = LOG.bind(stack_id=self.stack_id)

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        stack_paths = StackPaths(proc_config)

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

        load_stack_ifg_pairs(proc_config)
        ifgs_list_file = stack_paths.ifg_pair_lists[0]
        if ifgs_list_file.exists():
            with open(ifgs_list_file) as fd:
                date_pairs = [dates.split(",") for dates in fd.read().splitlines()]
                ifgs_pairs = [(Path(d1), Path(d2)) for d1, d2 in date_pairs]

            for primary_date, secondary_date in ifgs_pairs:
                ic = InterferogramPaths(proc_config, primary_date, secondary_date)

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
            for status_out in tdir(self.workdir).glob("*_ifg_*_status_logs.out"):
                with status_out.open("r") as file:
                    contents = file.read().splitlines()

                if len(contents) > 0 and "FAILED" in contents[0]:
                    primary_date, secondary_date = (Path(d) for d in re.split("[-_]", status_out.stem)[-4:-2])

                    log.info(f"Resuming IFG ({primary_date},{secondary_date}) because of FAILED processing")
                    reprocess_pairs.append((primary_date, secondary_date))

        reprocess_pairs = list(set(reprocess_pairs))

        # Any pairs that need reprocessing, we remove the status file of + clean the tree
        for primary_date, secondary_date in reprocess_pairs:
            status_file = tdir(self.workdir) / f"{self.stack_id}_ifg_{primary_date}-{secondary_date}_status_logs.out"

            # Remove Luigi status file
            if status_file.exists():
                status_file.unlink()

        return reprocess_pairs

    def run(self) -> Generator[List[ProcessIFG], None, None]:

        log = LOG.bind(stack_id=self.stack_id)
        log.info("Process interferograms task")

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
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
                    stack_id=self.stack_id,
                    outdir=self.outdir,
                    workdir=self.workdir,
                    primary_date=primary_date,
                    secondary_date=secondary_date,
                )
            )

        yield jobs

        with self.output().open("w") as f:
            f.write("")
