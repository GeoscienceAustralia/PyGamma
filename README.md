## GAMMA-INSAR

A tool to process Sentinel-1 SLC to Analysis Ready Data using GAMMA SOFTWARE.

## Installation
To install into a local user directory in NCI.
    
    python setup.py install --user 

To install into a particular path.
    
    export PYTHONPATH=<path/to/install/location/lib/python_version/site-packages>:$PYTHONPATH
    python setup.py install --prefix=<path/to/install/location> 

Python 3.6+ is supported.

## Operating System tested
Linux

## Supported Satellites and Sensors
* Sentinel-1A/B

## Requirements
* [attrs>=17.4.0]
* [Click>=7.0]
* [GDAL>=2.4]
* [geopandas>=0.4.1]
* [luigi>=2.8.3]
* [matplotlib>=3.0.3]
* [numpy>=1.8]
* [pandas>-0.24.2]
* [pyyaml>=3.11]
* [rasterio>=1,!=1.0.3.post1,!=1.0.3]
* [structlog>=16.1.0]
* [shapely>=1.5.13]
* [spatialist==0.4]
* [eodatasets3]
* [GAMMA-SOFTWARE >= June 2019 release]


## NCI Module
    
	$module use <path/to/a/module/file/location>
	$module load <module name>

### Usage
#### Single Stack processing 
The workflow is managed by a luigi-scheduler and parameters can be set in `luigi.cfg` file.

Process a single stack Sentinel-1 SLC data to directly using a ARD pipeline from the command line.

	$gamma_insar ARD --help

	usage: gamma_insar ARD
		   [REQUIRED PARAMETERS]
		   --vector-file-list    PATH    A full path to a Sentinel-1 tract and frame vector-file.
		   --start-date [%Y-%m-%d]  A start-date of SLC data acquisition.
		   --end-date [%Y-%m-%d]    An end-date of SLC data acquisition.
		   --workdir    PATH    A full path to a working directory to output logs.
		   --outdir PATH    A full path to an output directory.
		   --polarization LIST      Polarizations to be processed ["VV"|"VH"|"VV","VH"].	
		   --cleanup TEXT   A flag[yes|no] to specify a clean up  of intermediary files. Highly recommended to cleanup to limit storage during production.
		   --database-name  PATH   A full path to SLC-metata database with burst informations.
		   --orbit  TEXT    A Sentinel-1 orbit [A|D].
		   --dem-img PATH   A full path to a Digital Elevation Model.
		   --multi-look INTEGER A multi-look value.
		   --poeorb-path    PATH    A full path to a directory with precise orbit file.
		   --resorb-path    PATH    A full path to a directory with restitution orbit file.
		   --workers    INTEGER Number of workers assigned to a luigi scheduler.
		   --local-scheduler    TEXT    only test using a `local-scheduler`.


#### Example 

	$gamma_insar ARD --vector-file <path-to-vector-file> --start-date <start-date> --end-date <end-date> --workdir <path-to-workdir> --outdir <path-to-outdir> --workers <number-of-workers> --local-scheduler 

#### Single stack packaging 
The packaging of a single stack Sentinel-1 ARD processed using `gamma_insar ARD` workflow.

    $package --help
    
    usage: package 
          [REQUIRED PARAMETERS]
          --track TEXT                   track name of the grid definition: `T001D`
          --frame TEXT                   Frame name of the grid definition: `F02S`
          --input-dir PATH               The base directory of InSAR datasets
          --pkgdir PATH                  The base output packaged directory.
          --product TEXT                 The product to be packaged: sar|insar
          --polarization <TEXT TEXT>...  Polarizations used in metadata consolidations
                                         for product.

#### Example 

	$package --track <track-name> --frame <frame-name> --input-dir <path-to-stack-folder> --pkgdir <path-to-pkg-output-dir> --product sar --polarization VV VH 


#### Multi-stack processing using PBS system
Batch processing of multiple stacks Sentinel-1 SLC data to ARD using PBS module in NCI.
The list of the full-path-to-vector-files in a `taskfile` is divided into number of batches (nodes)
and submitted to NCI queue with parameters specified in a `required parameters`

    $pbs-insar --help 
    
    usage:  pbs-insar
            [REQUIRED PARAMETERS]
             --taskfile PATH    The file containing the list of tasks (full paths to vector-files) to beperformed
             --start-date  [%Y-%m-%d|%Y-%m-%dT%H:%M:%S|%Y-%m-%d %H:%M:%S]  The start date of SLC acquisition
             --end-date    [%Y-%m-%d|%Y-%m-%dT%H:%M:%S|%Y-%m-%d %H:%M:%S]  The end date of SLC acquisition
             --workdir PATH    The base working and scripts output directory.
             --outdir  PATH    The output directory for processed data
             --ncpus   INTEGER The total number of cpus per job required if known(default=48)
             --memory  INTEGER Total memory required if per node
             --queue   TEXT    Queue to submit the job into (default=normal)
             --hours   INTEGER Job walltime in hours (default=48)
             --email   TEXT    Notification email address.
             --nodes   INTEGER Number of nodes to be requested(default=1)
             --jobfs   INTEGER Jobfs required per node (default=400)
             -s, --storage TEXT    Project storage you wish to use in PBS jobs
             --project TEXT        Project to compute under
             --env PATH            Environment script to source.
             --test                Mock the job submission to PBS queue

#### Example 

	$pbs-insar --taskfile <path-to-taskfile> --start-date <start-date> --end-date <end-date> --workdir <path-to-workdir> --outdir <path-to-outdir> --ncpus 48 --memory 192 --queue normal --nodes 2 --jobfs 400 -s <project1> -s <project2> --project <project-name> --env <path-to-envfile> 

#### Multi-stack packaging of InSAR ARD using PBS system
Batch processing of packaging of InSAR ARD to be indexed using Open Data Cube tools eo-datasets. 
The `input-list` containing the full path to stack processed can be submitted to NCI PBS system 
to be packaged to be indexed into a data-cube. 

    $pbs-package --help 
    
    usage pbs-package
       [REQUIRED PARAMETERS]
      --input-list PATH              full path to a file with list of track and
                                     frames to be packaged
      --workdir PATH                 The base working and scripts output
                                     directory.
      --pkgdir PATH                  The output directory for packaged data
      --ncpus INTEGER                The total number of cpus per noderequired if
                                     known
      --memory INTEGER               Total memory required per node
      --queue TEXT                   Queue to submit the job into
      --hours INTEGER                Job walltime in hours.
      --jobfs INTEGER                jobfs required per node
      -s, --storage TEXT             Project storage you wish to use in PBS jobs
      --project TEXT                 Project to compute under  [required]
      --env PATH                     Environment script to source.  [required]
      --product TEXT                 The product to be packaged: sar| insar
      --polarization <TEXT TEXT>...  Polarizations used in metadata consolidations
                                     for product.
      --test                         mock the job submission to PBS queue

#### Example 

	$pbs-package --input-list <path-to-input-list> --workdir <path-to-workdir> --pkgdir <path-to-pkgdir> --ncpus 8--memory 32 --product sar --polarization VV VH --queue normal --nodes 2 --jobfs 50 -s <project1> -s <project2> --project <project-name> --env <path-to-envfile> 
