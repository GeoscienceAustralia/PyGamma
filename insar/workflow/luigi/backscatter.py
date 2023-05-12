from pathlib import Path
from typing import List
import luigi
import luigi.configuration
from luigi.util import requires
import structlog

from insar.constant import SCENE_DATE_FMT
from insar.project import ProcConfig
from insar.process_backscatter import generate_normalised_backscatter
from insar.logs import STATUS_LOGGER as LOG

from insar.workflow.luigi.utils import PathParameter, tdir, read_rlks_alks, read_primary_date
from insar.workflow.luigi.coregistration import CreateCoregisterSecondaries, get_coreg_kwargs, get_coreg_date_pairs


class ProcessBackscatter(luigi.Task):
    """
    Produces the NBR (normalised radar backscatter) product for an SLC.
    """

    proc_file = PathParameter()
    outdir = PathParameter()
    workdir = PathParameter()

    src_mli = PathParameter()
    ellip_pix_sigma0 = PathParameter()
    dem_pix_gamma0 = PathParameter()
    dem_lt_fine = PathParameter()
    geo_dem_par = PathParameter()
    dst_stem = PathParameter()

    def output(self):
        return luigi.LocalTarget(tdir(self.workdir) / f"{Path(str(self.src_mli)).stem}_nbr_logs.out")

    def run(self):
        slc_date, slc_pol = Path(self.src_mli).stem.split("_")[:2]
        slc_date = slc_date.lstrip("r")

        LOG.info(f"Beginning normalised radar backscatter for {self.src_mli} and date {slc_date}")

        # Load the gamma proc config file
        with open(str(self.proc_file), "r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        failed = False

        try:
            structlog.threadlocal.clear_threadlocal()
            structlog.threadlocal.bind_threadlocal(
                task="Normalised radar backscatter", scene_dir=self.outdir, scene_date=slc_date, polarisation=slc_pol
            )


            generate_normalised_backscatter(
                Path(self.outdir),
                Path(self.src_mli),
                Path(self.ellip_pix_sigma0),
                Path(self.dem_pix_gamma0),
                Path(self.dem_lt_fine),
                Path(self.geo_dem_par),
                Path(self.dst_stem),
            )

            LOG.info(f"Normalised radar backscatter complete for {self.src_mli} and date {slc_date}")

        except Exception as e:
            log.error("Normalised radar backscatter for {self.src_mli} and date {slc_date} failed with exception", exc_info=True)
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
    Runs the backscatter tasks for all coregistered scenes,
    as well as the primary reference scene used for coreg.
    """

    proc_file = PathParameter()
    polarization = luigi.ListParameter(default=None)

    def output(self):
        return luigi.LocalTarget(tdir(self.workdir) / f"{self.stack_id}_backscatter_status_logs.out")

    def get_create_coreg_task(self):
        log = STATUS_LOGGER.bind(stack_id=self.stack_id)

        # Note: We share identical parameters, so we just forward them a copy
        kwargs = {k: getattr(self, k) for k, _ in self.get_params()}

        return CreateCoregisterSecondaries(**kwargs)

    def trigger_resume(self, reprocess_dates: List[str], reprocess_failed_scenes: bool):
        log = STATUS_LOGGER.bind(stack_id=self.stack_id)

        # All we need to do is drop our outputs, as the backscatter
        # task can safely over-write itself...
        if self.output().exists():
            self.output().remove()

        # Remove completion status files for any failed SLC coreg tasks
        triggered_dates = []

        nbr_outfile_pattern = "*_nbr_logs.out"
        nbr_outfile_suffix_len = len(nbr_outfile_pattern) - 1

        if reprocess_failed_scenes:
            for status_out in tdir(self.workdir).glob(nbr_outfile_pattern):
                mli = status_out.name[:-nbr_outfile_suffix_len] + ".mli"
                scene_date = mli.split("_")[0].lstrip("r")

                with status_out.open("r") as file:
                    contents = file.read().splitlines()

                if len(contents) > 0 and "FAILED" in contents[0]:
                    triggered_dates.append(scene_date)

                    log.info(f"Resuming SLC backscatter ({mli}) because of FAILED processing")
                    status_out.unlink()

        # Remove completion status files for any we're asked to
        for date in reprocess_dates:
            for status_out in tdir(self.workdir).glob(f"*{date}_" + nbr_outfile_pattern):
                mli = status_out.name[:-nbr_outfile_suffix_len] + ".mli"
                scene_date = mli.split("_")[0].lstrip("r")

                triggered_dates.append(scene_date)

                log.info(f"Resuming SLC backscatter ({mli}) because of dependency")
                status_out.unlink()

        return triggered_dates

    def run(self):
        LOG.info(f"Starting Coregistered SLC backscatter ({self.stack_id})")

        outdir = Path(self.outdir)

        # Load the gamma proc config file
        proc_path = Path(self.proc_file)
        with proc_path.open("r") as proc_fileobj:
            proc_config = ProcConfig.from_file(proc_fileobj)

        # get range and azimuth looked values
        ml_file = tdir(self.workdir) / f"{self.stack_id}_createmultilook_status_logs.out"
        rlks, alks = read_rlks_alks(ml_file)

        coreg_kwargs = get_coreg_kwargs(proc_path)

        kwargs = {
            "proc_file": self.proc_file,
            "outdir": self.outdir,
            "workdir": self.workdir,
            "ellip_pix_sigma0": coreg_kwargs["ellip_pix_sigma0"],
            "dem_pix_gamma0": coreg_kwargs["dem_pix_gamma0"],
            "dem_lt_fine": coreg_kwargs["dem_lt_fine"],
            "geo_dem_par": coreg_kwargs["geo_dem_par"],
        }

        jobs = []

        # Create backscatter for primary reference scene
        # we do this even though it's not coregistered

        primary_scene = read_primary_date(outdir).strftime(SCENE_DATE_FMT)
        primary_dir = outdir / proc_config.slc_dir / primary_scene
        primary_pol = proc_config.polarisation.upper()

        LOG.info(f"Creating Backscatter task for primary reference scene {primary_scene}")

        for pol in list(self.polarization):
            prefix = f"{primary_scene}_{pol.upper()}_{rlks}rlks"

            # Note: primary date has no coregistered/resampled files
            # since it 'is' the reference date for coreg, this we
            # use the plain old multisampled SLC for this date.
            kwargs["outdir"] = primary_dir
            kwargs["src_mli"] = primary_dir / f"{prefix}.mli"
            kwargs["dst_stem"] = primary_dir / f"{prefix}"

            LOG.info(f"Creating Backscatter processing task ({kwargs})")

            task = ProcessBackscatter(**kwargs)
            jobs.append(task)


        coreg_date_pairs = get_coreg_date_pairs(outdir, proc_config)

        for _, secondary_date in coreg_date_pairs:
            secondary_dir = outdir / proc_config.slc_dir / secondary_date

            LOG.info(f"Creating Backscatter task for secondary coregistered scene {secondary_date}")

            for pol in list(self.polarization):
                prefix = f"{secondary_date}_{pol.upper()}_{rlks}rlks"

                kwargs["outdir"] = secondary_dir
                kwargs["src_mli"] = secondary_dir / f"r{prefix}.mli"
                # TBD: We have always written the backscatter w/ the same
                # pattern, but going forward we might want coregistered
                # backscatter to also have the 'r' prefix?  as some
                # backscatters in the future will 'not' be coregistered...
                kwargs["dst_stem"] = secondary_dir / f"{prefix}"


                task = ProcessBackscatter(**kwargs)
                jobs.append(task)

        yield jobs

        with self.output().open("w") as f:
            f.write("")
