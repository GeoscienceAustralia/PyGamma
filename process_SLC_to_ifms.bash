#!/bin/bash

display_usage() {
    echo ""
    echo "*******************************************************************************"
    echo "* process_SLC_to_ifms:  Script uses options in a parameter file to run the    *"
    echo "*                       GAMMA interferogram processing chain (ie. make SLCs,  *"
    echo "*                       coregister DEM, coregister slaves, make ifms).        *"
    echo "*                                                                             *"
    echo "* input:  [proc_file]  name of GAMMA proc file (eg. gamma.proc)               *"
    echo "*                                                                             *"
    echo "* author: Sarah Lawrie @ GA       01/05/2015, v1.0                            *"
    echo "*******************************************************************************"
    echo -e "Usage: process_SLC_to_ifms.bash [proc_file]"
    }

if [ $# -lt 1 ]
then 
    display_usage
    exit 1
fi

proc_file=$1

## Variables from parameter file (*.proc)
platform=`grep Platform= $proc_file | cut -d "=" -f 2`
project=`grep Project= $proc_file | cut -d "=" -f 2`
sensor=`grep Sensor= $proc_file | cut -d "=" -f 2`
do_setup=`grep Setup= $proc_file | cut -d "=" -f 2`
do_raw=`grep Do_raw_data= $proc_file | cut -d "=" -f 2` 
do_slc=`grep Do_SLC= $proc_file | cut -d "=" -f 2`
coregister_dem=`grep Coregister_DEM= $proc_file | cut -d "=" -f 2`
coregister=`grep Coregister_slaves= $proc_file | cut -d "=" -f 2`
do_ifms=`grep Process_ifms= $proc_file | cut -d "=" -f 2`
add_slc=`grep Add_new_SLC= $proc_file | cut -d "=" -f 2`
recoregister_dem=`grep Re-coregister_DEM= $proc_file | cut -d "=" -f 2`
coregister_add=`grep Coregister_add_slaves= $proc_file | cut -d "=" -f 2`
do_add_ifms=`grep Process_add_ifms= $proc_file | cut -d "=" -f 2`
track_dir=`grep Track= $proc_file | cut -d "=" -f 2`
frame_list=`grep List_of_frames= $proc_file | cut -d "=" -f 2`
mas=`grep Master_scene= $proc_file | cut -d "=" -f 2`
slc_looks=`grep SLC_multi_look= $proc_file | cut -d "=" -f 2`
ifm_looks=`grep ifm_multi_look= $proc_file | cut -d "=" -f 2`
polar=`grep Polarisation= $proc_file | cut -d "=" -f 2`
palsar1_data=`grep PALSAR1_data= $proc_file | cut -d "=" -f 2`
subset=`grep Subsetting= $proc_file | cut -d "=" -f 2`
subset_done=`grep Subsetting_done= $proc_file | cut -d "=" -f 2`
roff=`grep range_offset= $proc_file | cut -d "=" -f 2`
rlines=`grep range_lines= $proc_file | cut -d "=" -f 2`
azoff=`grep azimuth_offset= $proc_file | cut -d "=" -f 2`
azlines=`grep azimuth_lines= $proc_file | cut -d "=" -f 2`
raw_dir_ga=`grep Raw_data_GA= $proc_file | cut -d "=" -f 2`
raw_dir_mdss=`grep Raw_data_MDSS= $proc_file | cut -d "=" -f 2`
list_walltime=`grep list_walltime= $proc_file | cut -d "=" -f 2`
list_mem=`grep list_mem= $proc_file | cut -d "=" -f 2`
list_ncpus=`grep list_ncpus= $proc_file | cut -d "=" -f 2`
raw_walltime=`grep raw_walltime= $proc_file | cut -d "=" -f 2`
raw_mem=`grep raw_mem= $proc_file | cut -d "=" -f 2`
raw_ncpus=`grep raw_ncpus= $proc_file | cut -d "=" -f 2`
slc_walltime=`grep SLC_walltime= $proc_file | cut -d "=" -f 2`
slc_mem=`grep SLC_mem= $proc_file | cut -d "=" -f 2`
slc_ncpus=`grep SLC_ncpus= $proc_file | cut -d "=" -f 2`
dem_walltime=`grep DEM_walltime= $proc_file | cut -d "=" -f 2`
dem_mem=`grep DEM_mem= $proc_file | cut -d "=" -f 2`
dem_ncpus=`grep DEM_ncpus= $proc_file | cut -d "=" -f 2`
co_slc_walltime=`grep coreg_walltime= $proc_file | cut -d "=" -f 2`
co_slc_mem=`grep coreg_mem= $proc_file | cut -d "=" -f 2`
co_slc_ncpus=`grep coreg_ncpus= $proc_file | cut -d "=" -f 2`
ifm_walltime=`grep ifm_walltime= $proc_file | cut -d "=" -f 2`
ifm_mem=`grep ifm_mem= $proc_file | cut -d "=" -f 2`
ifm_ncpus=`grep ifm_ncpus= $proc_file | cut -d "=" -f 2`
geo_walltime=`grep geo_walltime= $proc_file | cut -d "=" -f 2`
geo_mem=`grep geo_mem= $proc_file | cut -d "=" -f 2`
geo_ncpus=`grep geo_ncpus= $proc_file | cut -d "=" -f 2`

## Identify project directory based on platform
if [ $platform == NCI ]; then
    proj_dir=/g/data1/dg9/INSAR_ANALYSIS/$project/$sensor/GAMMA
else
    proj_dir=/nas/gemd/insar/INSAR_ANALYSIS/$project/$sensor/GAMMA
fi

cd $proj_dir

## Add carriage return to last line of frame.list file if it exists (required for loops to work)
if [ -f $frame_list ]; then
    echo >> $frame_list
else
    :
fi

## Insert scene details top of NCI .e file
echo "" 1>&2 # adds spaces at top so scene details are clear
echo "" 1>&2
echo "PROCESSING_PROJECT: "$project $track_dir 1>&2

## Copy output of Gamma programs to log files
#GM()
#{
#    echo $* | tee -a command.log
#    echo
#    $* >> output.log 2> temp_log
#    cat temp_log >> error.log
    #cat output.log (option to add output results to NCI .o file if required)
#}

## Load GAMMA based on platform
if [ $platform == NCI ]; then
    GAMMA=`grep GAMMA_NCI= $proc_file | cut -d "=" -f 2`
    source $GAMMA
else
    GAMMA=`grep GAMMA_GA= $proc_file | cut -d "=" -f 2`
    source $GAMMA
fi

slc_dir=$proj_dir/$track_dir/`grep SLC_dir= $proc_file | cut -d "=" -f 2`
dem_dir=$proj_dir/$track_dir/`grep DEM_dir= $proc_file | cut -d "=" -f 2`
ifm_dir=$proj_dir/$track_dir/`grep INT_dir= $proc_file | cut -d "=" -f 2`
frame_list=$proj_dir/$track_dir/`grep List_of_frames= $proc_file | cut -d "=" -f 2`
scene_list=$proj_dir/$track_dir/`grep List_of_scenes= $proc_file | cut -d "=" -f 2`
slave_list=$proj_dir/$track_dir/`grep List_of_slaves= $proc_file | cut -d "=" -f 2`
ifm_list=$proj_dir/$track_dir/`grep List_of_ifms= $proc_file | cut -d "=" -f 2`
add_scene_list=$proj_dir/$track_dir/`grep List_of_add_scenes= $proc_file | cut -d "=" -f 2`
add_slave_list=$proj_dir/$track_dir/`grep List_of_add_slaves= $proc_file | cut -d "=" -f 2`
add_ifm_list=$proj_dir/$track_dir/`grep List_of_add_ifms= $proc_file | cut -d "=" -f 2`

## Determine range and azimuth looks
if [ $sensor == ASAR -o $sensor = ERS ]; then
    slc_rlks=$slc_looks 
    slc_alks=`echo $slc_looks | awk '{print $1*5}'` 
    ifm_rlks=$ifm_looks 
    ifm_alks=`echo $ifm_looks | awk '{print $1*5}'` 
elif [ $sensor == JERS1 ]; then
    slc_rlks=$slc_looks 
    slc_alks=`echo $slc_looks | awk '{print $1*3}'` 
    ifm_rlks=$ifm_looks 
    ifm_alks=`echo $ifm_looks | awk '{print $1*3}'`
elif [ $sensor == RSAT1 ]; then
    slc_rlks=$slc_looks 
    slc_alks=`echo $slc_looks | awk '{print $1*4}'` 
    ifm_rlks=$ifm_looks 
    ifm_alks=`echo $ifm_looks | awk '{print $1*4}'` 
elif [ $sensor == PALSAR1 -o $sensor == PALSAR2 ]; then
    slc_rlks=$slc_looks 
    slc_alks=`echo $slc_looks | awk '{print $1*2}'` 
    ifm_rlks=$ifm_looks 
    ifm_alks=`echo $ifm_looks | awk '{print $1*2}'`
else
    # CSK, RSAT2, S1, TSX
    slc_rlks=$slc_looks
    slc_alks=$slc_looks
    ifm_rlks=$ifm_looks
    ifm_alks=$ifm_looks
fi

err_dir=$proj_dir/$track_dir/Error_Files

##### SETUP PROJECT DIRECTORY STRUCTURE AND LISTS FOR PROCESSING #####

## GA ##
if [ $do_setup == yes -a $platform == GA ]; then
# create track dir
    echo " "
    echo "Creating project directory structure..."
    mkdir -p $track_dir
    mkdir -p $err_dir
    if [ -f frame.list ]; then # if multiple frames exist
	mv frame.list $track_dir
    fi
# create scenes.list file
    cd $raw_dir_ga
    echo "Creating scenes list file..."
    create_scenes_list.bash $proj_dir/$proc_file
# create slaves.list file
    cd $proj_dir/$track_dir
    echo "Creating slaves list file..."
    create_slaves_list.bash $proj_dir/$proc_file
# create ifms.list file
    echo "Creating interferogram list file..."
    create_ifms_list.bash $proj_dir/$proc_file
    echo "Setup complete for "$project $sensor $track_dir"."
    echo " "
elif [ $do_setup == no -a $platform == GA ]; then
    echo " "
    echo "Option to setup project directories and lists not selected."
    echo " "
## NCI ###
elif [ $do_setup == yes -a $platform == NCI ]; then
    cd $proj_dir
    mkdir -p $track_dir # GAMMA processing directory
    mkdir -p $track_dir/batch_scripts # for PBS jobs
    mkdir -p raw_data # raw data directory
    mkdir -p raw_data/$track_dir
    if [ -f frame.list ]; then
	while read frame; do
	    if [ ! -z $frame ]; then # skips any empty lines
		mkdir -p raw_data/$track_dir/F$frame
	    fi
	done < frame.list
    else
	:
    fi
    if [ -f frame.list ]; then
	mv frame.list $track_dir
    else
	:
    fi
# create scenes.list file
    cd $proj_dir/$track_dir/batch_scripts
    sc_list=sc_list_gen
    echo \#\!/bin/bash > $sc_list
    echo \#\PBS -lother=gdata1 >> $sc_list
    echo \#\PBS -l walltime=$list_walltime >> $sc_list
    echo \#\PBS -l mem=$list_mem >> $sc_list
    echo \#\PBS -l ncpus=$list_ncpus >> $sc_list
    echo \#\PBS -l wd >> $sc_list
    echo \#\PBS -q copyq >> $sc_list
    echo ~/repo/gamma_bash/create_scenes_list.bash $proj_dir/$proc_file >> $sc_list
    chmod +x $sc_list
    qsub $sc_list | tee sc_list_job_id
# create slaves.list file
    sc_list_jobid=`sed s/.r-man2// sc_list_job_id`
    slv_list=slv_list_gen
    echo \#\!/bin/bash > $slv_list
    echo \#\PBS -lother=gdata1 >> $slv_list
    echo \#\PBS -l walltime=$list_walltime >> $slv_list
    echo \#\PBS -l mem=$list_mem >> $slv_list
    echo \#\PBS -l ncpus=$list_ncpus >> $slv_list
    echo \#\PBS -l wd >> $slv_list
    echo \#\PBS -q express >> $slv_list
    echo \#\PBS -W depend=afterok:$sc_list_jobid >> $slv_list
    echo ~/repo/gamma_bash/create_slaves_list.bash $proj_dir/$proc_file >> $slv_list
    chmod +x $slv_list
    qsub $slv_list
# create ifms.list file
    ifm_list=ifm_list_gen
    echo \#\!/bin/bash > $ifm_list
    echo \#\PBS -lother=gdata1 >> $ifm_list
    echo \#\PBS -l walltime=$list_walltime >> $ifm_list
    echo \#\PBS -l mem=$list_mem >> $ifm_list
    echo \#\PBS -l ncpus=$list_ncpus >> $ifm_list
    echo \#\PBS -l wd >> $ifm_list
    echo \#\PBS -q express >> $ifm_list
    echo \#\PBS -W depend=afterok:$sc_list_jobid >> $ifm_list
    echo ~/repo/gamma_bash/create_ifms_list.bash $proj_dir/$proc_file >> $ifm_list
    chmod +x $ifm_list
    qsub $ifm_list
else
    :
fi


##### EXTRACT RAW AND DEM DATA #####

## GA 
if [ $do_raw == yes -a $platform == GA ]; then
    cd $proj_dir/$track_dir
    echo "Extracting raw data..."
    echo " "
    extract_raw_data.bash $proj_dir/$proc_file
elif [ $do_raw == no -a $platform == GA ]; then
    echo " "
    echo "Option to extract raw data not selected."
    echo " "
else
    :
fi
## NCI ##
if [ $do_raw == yes -a $platform == NCI ]; then
    cd $proj_dir/$track_dir/batch_scripts
    raw=extract_raw 
    echo \#\!/bin/bash > $raw
    echo \#\PBS -lother=gdata1 >> $raw
    echo \#\PBS -l walltime=$raw_walltime >> $raw
    echo \#\PBS -l mem=$raw_mem >> $raw
    echo \#\PBS -l ncpus=$raw_ncpus >> $raw
    echo \#\PBS -l wd >> $raw
    echo \#\PBS -q copyq >> $raw
    if [ $do_setup == yes -a $platform == NCI ]; then # needs scene.list to be created first if it doesn't exist
	echo \#\PBS -W depend=afterok:$sc_list_jobid >> $raw
    else
	:
    fi
    echo ~/repo/gamma_bash/extract_raw_data.bash $proj_dir/$proc_file >> $raw
    chmod +x $raw
    qsub $raw | tee raw_job_id
else
    :
fi


##### CREATE SLC DATA #####

## GA ##
if [ $do_slc == yes ]; then
    if [ $palsar1_data == raw -a $sensor == PALSAR1 ]; then
	sensor=PALSAR_L0 # PALSAR L1.0 script can process PALSAR1 raw data
    elif [ $palsar1_data == slc -a $sensor == PALSAR1 ]; then
	sensor=PALSAR_L1 # PALSAR L1.1 script can process both PALSAR1 and PALSAR2 slc level data
    elif [ $sensor == PALSAR2 ]; then
        sensor=PALSAR_L1
    else
	:
    fi
fi
if [ $do_slc == yes -a $platform == GA ]; then
    cd $proj_dir
# consolidate error logs into one file
    err_log=$err_dir/SLC_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_SLC_Creation_Error_Log" > $err_log
    echo " " >> $err_log
    echo "Creating SLC data..."
# SLC and ifm multi-look value (same value)
    if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	while read scene; do
	    if [ ! -z $scene ]; then
		echo " "
		echo "Creating SLC for "$scene" with "$slc_rlks" range and "$slc_alks" azimuth looks..."
		process_$sensor"_SLC.bash" $proj_dir/$proc_file $scene $slc_rlks $slc_alks
		cd $slc_dir/$scene
		echo " " >> $err_log
		echo "Creating SLC for "$scene" with "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
	    fi
	done < $scene_list
    else
	while read scene; do
	    if [ ! -z $scene ]; then
 # SLC multi-look value
		echo " "
		echo "Creating SLC for "$scene" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks..."
		process_$sensor"_SLC.bash" $proj_dir/$proc_file $scene $slc_rlks $slc_alks
		cd $slc_dir/$scene
		echo " " >> $err_log
		echo "Creating SLC for "$scene" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
# ifm multi-look value
		echo " "
		echo "Creating SLC for "$scene" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks..."
		process_$sensor"_SLC.bash" $proj_dir/$proc_file $scene $ifm_rlks $ifm_alks
		cd $slc_dir/$scene
		echo " " >> $err_log
		echo "Creating SLC for "$scene" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
	    fi
	done < $scene_list
    fi
    echo " "
    echo "SLC processing completed."
    echo " "
elif [ $do_slc == no -a $platform == GA ]; then
    echo " "
    echo "Option to create SLC data not selected."
    echo " "
## NCI ##
elif [ $do_slc == yes -a $platform == NCI ]; then
    cd $proj_dir/$track_dir/batch_scripts
    # set up and submit PBS job script for each SLC
    while read scene; do
	if [ ! -z $scene ]; then
	    raw_jobid=`sed s/.r-man2// raw_job_id`
	    slc_script=slc_$scene
	    rm -rf $slc_script
	    echo \#\!/bin/bash > $slc_script
	    echo \#\PBS -lother=gdata1 >> $slc_script
	    echo \#\PBS -l walltime=$slc_walltime >> $slc_script
	    echo \#\PBS -l mem=$slc_mem >> $slc_script
	    echo \#\PBS -l ncpus=$slc_ncpus >> $slc_script
	    echo \#\PBS -l wd >> $slc_script
	    echo \#\PBS -q normal >> $slc_script
	    if [ $do_raw == yes -a $platform == NCI ]; then # needs raw data extracted first if it hasn't already
		echo \#\PBS -W depend=afterok:$raw_jobid >> $slc_script
	    else
		:
	    fi
	    echo ~/repo/gamma_bash/"process_"$sensor"_SLC.bash" $proj_dir/$proc_file $scene >> $slc_script
	    chmod +x $slc_script
#            qsub $slc_script | tee slc_job_id
	fi
    done < $scene_list
    slc_jobid=`sed s/.r-man2// slc_job_id`
    slc_errors=slc_err_check
    rm -rf $slc_errors
    echo \#\!/bin/bash > $slc_errors
    echo \#\PBS -lother=gdata1 >> $slc_errors
    echo \#\PBS -l walltime=00:15:00 >> $slc_errors
    echo \#\PBS -l mem=500MB >> $slc_errors
    echo \#\PBS -l ncpus=1 >> $slc_errors
    echo \#\PBS -l wd >> $slc_errors
    echo \#\PBS -q normal >> $slc_errors
    echo \#\PBS -W depend=afterok:$slc_jobid >> $slc_errors
    echo ~/repo/gamma_bash/collate_nci_slc_errors.bash $proc_file >> $slc_errors
    chmod +x $slc_errors
#    qsub $slc_errors | tee slc_errors_job_id
else
    :
fi


##### COREGISTER DEM TO MASTER SCENE #####

## GA ##
if [ $coregister_dem == yes -a $platform == GA ]; then
    cd $proj_dir
# consolidate error log into one file
    err_log=$err_dir/DEM_coreg_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_Coregister_DEM_Error_Log" > $err_log
    echo " " >> $err_log
    echo " " >> $err_log
    echo "Coregistering DEM to master scene..."
    if [ $subset == yes -a $subset_done == notyet ]; then 
       # no multi-look value - for geocoding full SLC and determining pixels for subsetting master scene
       echo "Coregistering DEM to master scene with 1 range and 1 azimuth looks..."
       make_ref_master_DEM.bash $proj_dir/$proc_file 1 1 2 - - - -
       cd $dem_dir
       echo "Coregistering DEM to master scene with 1 range and 1 azimuth looks" >> $err_log
       less error.log > temp
       # remove unecessary lines from error log
       sed '/^scene/ d' temp > temp2 
       sed '/^USAGE/ d' temp2 >> $err_log
       grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
       echo " " >> $err_log
       echo " " >> $err_log
       rm -f temp temp2
       echo " "
       echo "Subsetting of master scene required, run xxx.bash to determine pixel coordinates before continuing."
       echo " "
       exit 0 # allow for subsettting calculations
   elif [ $subset == yes -a $subset_done == process ]; then 
	echo " "
	echo "Subsetting master scene..."
	echo " "
        # no multi-look value - for geocoding full SLC data
	echo "Coregistering DEM to master scene with 1 range and 1 azimuth looks..."
	make_ref_master_DEM.bash $proj_dir/$proc_file 1 1 2 $roff $rlines $azoff $azlines
	cd $dem_dir
	echo "Coregistering DEM to master scene with 1 range and 1 azimuth looks" >> $err_log
	less error.log > temp
        # remove unecessary lines from error log
	sed '/^scene/ d' temp > temp2 
	sed '/^USAGE/ d' temp2 >> $err_log
	grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	echo " " >> $err_log
	echo " " >> $err_log
	rm -f temp temp2
        # SLC and ifm multi-look value (same value)
	if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	    echo "Coregistering DEM to master scene with "$slc_rlks" range and "$slc_alks" azimuth looks..."
	    cd $proj_dir
	    make_ref_master_DEM.bash $proj_dir/$proc_file $slc_rlks $slc_alks 1 $roff $rlines $azoff $azlines
	    cd $dem_dir
	    echo " " >> $err_log
	    echo "Coregistering DEM to master scene with "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
	    less error.log > temp
            # remove unecessary lines from error log
	    sed '/^scene/ d' temp > temp2 
	    sed '/^USAGE/ d' temp2 >> $err_log
	    grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	    echo " " >> $err_log
	    echo " " >> $err_log
	    rm -f temp temp2
	else
            # SLC multi-look value
	    echo "Coregistering DEM to master scene with SLC "$slc_rlks" range and "$slc_alks" azimuth looks..."
	    cd $proj_dir
	    make_ref_master_DEM.bash $proj_dir/$proc_file $slc_rlks $slc_alks 1 $roff $rlines $azoff $azlines
	    cd $dem_dir
	    echo " " >> $err_log
	    echo " " >> $err_log
	    echo "Coregistering DEM to master scene with SLC "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
	    less error.log > temp
            # remove unecessary lines from error log
	    sed '/^scene/ d' temp > temp2 
	    sed '/^USAGE/ d' temp2 >> $err_log
	    grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	    echo " " >> $err_log
	    echo " " >> $err_log
	    rm -f temp temp2
            # ifm multi-look value
	    echo "Coregistering DEM to master scene with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks..."
	    cd $proj_dir
	    make_ref_master_DEM.bash $proj_dir/$proc_file $ifm_rlks $ifm_alks 1 $roff $rlines $azoff $azlines
	    cd $dem_dir
	    echo " " >> $err_log
	    echo " " >> $err_log
	    echo "Coregistering DEM to master scene with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks" >> $err_log
	    less error.log > temp
            # remove unecessary lines from error log
	    sed '/^scene/ d' temp > temp2 
	    sed '/^USAGE/ d' temp2 >> $err_log
	    grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	    echo " " >> $err_log
	    echo " " >> $err_log
	    rm -f temp temp2
	fi
    elif [ $subset == no ]; then # no subsetting 
        # no multi-look value - for geocoding full SLC data
	echo "Coregistering DEM to master scene with 1 range and 1 azimuth looks..."
	make_ref_master_DEM.bash $proj_dir/$proc_file 1 1 2 - - - -
	cd $dem_dir
	echo "Coregistering DEM to master scene with 1 range and 1 azimuth looks" >> $err_log
	less error.log > temp
        # remove unecessary lines from error log
	sed '/^scene/ d' temp > temp2 
	sed '/^USAGE/ d' temp2 >> $err_log
	grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	echo " " >> $err_log
	echo " " >> $err_log
	rm -f temp temp2
        # SLC and ifm multi-look value (same value)
	if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	    echo "Coregistering DEM to master scene with "$slc_rlks" range and "$slc_alks" azimuth looks..."
	    cd $proj_dir
	    make_ref_master_DEM.bash $proj_dir/$proc_file $slc_rlks $slc_alks 1 $roff $rlines $azoff $azlines
	    cd $dem_dir
	    echo " " >> $err_log
	    echo "Coregistering DEM to master scene with "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
	    less error.log > temp
        # remove unecessary lines from error log
	    sed '/^scene/ d' temp > temp2 
	    sed '/^USAGE/ d' temp2 >> $err_log
	    grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	    echo " " >> $err_log
	    echo " " >> $err_log
	    rm -f temp temp2
	else
            # SLC multi-look value
	    echo "Coregistering DEM to master scene with SLC "$slc_rlks" range and "$slc_alks" azimuth looks..."
	    cd $proj_dir
	    make_ref_master_DEM.bash $proj_dir/$proc_file $slc_rlks $slc_alks 1 $roff $rlines $azoff $azlines
	    cd $dem_dir
	    echo " " >> $err_log
	    echo " " >> $err_log
	    echo "Coregistering DEM to master scene with SLC "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
	    less error.log > temp
            # remove unecessary lines from error log
	    sed '/^scene/ d' temp > temp2 
	    sed '/^USAGE/ d' temp2 >> $err_log
	    grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	    echo " " >> $err_log
	    echo " " >> $err_log
	    rm -f temp temp2
            # ifm multi-look value
	    echo "Coregistering DEM to master scene with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks..."
	    cd $proj_dir
	    make_ref_master_DEM.bash $proj_dir/$proc_file $ifm_rlks $ifm_alks 1 $roff $rlines $azoff $azlines
	    cd $dem_dir
	    echo " " >> $err_log
	    echo " " >> $err_log
	    echo "Coregistering DEM to master scene with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks" >> $err_log
	    less error.log > temp
        # remove unecessary lines from error log
	    sed '/^scene/ d' temp > temp2 
	    sed '/^USAGE/ d' temp2 >> $err_log
	    grep "correlation SNR:" output.log >> $err_log # will appear if SNR is below threshold
	    echo " " >> $err_log
	    echo " " >> $err_log
	    rm -f temp temp2
	fi
    else
	:
    fi
    echo " "
    echo "Coregistering DEM to master scene completed."
    echo " "
elif [ $coregister_dem == no -a $platform == GA ]; then
    echo " "
    echo "Option to coregister DEM to master scene not selected."
    echo " "
## NCI ##
elif [ $coregister_dem == yes -a $platform == NCI ]; then
    cd $proj_dir/$track_dir/batch_scripts
    slc_jobid=`sed s/.r-man2// slc_job_id`
    # set up header for PBS job
    if [ -e coregister_dem ]; then 
	rm -rf coregister_dem
    fi
    dem=coregister_dem
    echo \#\!/bin/bash > $dem
    echo \#\PBS -lother=gdata1 >> $dem
    echo \#\PBS -l walltime=$dem_walltime >> $dem
    echo \#\PBS -l mem=$dem_mem >> $dem
    echo \#\PBS -l ncpus=$dem_ncpus >> $dem
    echo \#\PBS -l wd >> $dem
    echo \#\PBS -q normal >> $dem
    if [ $do_slc == yes ]; then
	echo \#\PBS -W depend=afterok:$slc_jobid >> $dem
    else
	:
    fi
    echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/make_ref_master_DEM.bash $proc_file 1 1 >> $dem
    if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/make_ref_master_DEM.bash $proc_file $slc_rlks $slc_alks >> $dem
    else
	echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/make_ref_master_DEM.bash $proc_file $slc_rlks $slc_alks >> $dem
	echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/make_ref_master_DEM.bash $proc_file $ifm_rlks $ifm_alks >> $dem
    fi
    chmod +x $dem
    qsub $dem | tee dem_job_id
else
    :
fi


##### COREGISTER SLAVE SCENES TO MASTER SCENE #####

## GA ##
if [ $coregister == yes -a $platform == GA ]; then
    cd $proj_dir
# consolidate error logs into one file
    err_log=$err_dir/SLC_coreg_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_Coregister_SLC_Error_Log" > $err_log
    echo " " >> $err_log
    echo "Coregistering slave scenes to master scene..."
# SLC and ifm multi-look value (same value)
    if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	while read date; do
	    if [ ! -z $date ]; then
		slave=`echo $date | awk 'BEGIN {FS=","} ; {print $1}'`
		echo "Coregistering "$slave" to master scene with "$slc_rlks" range and "$slc_alks" azimuth looks..."
		coregister_slave_SLC.bash $proj_dir/$proc_file $slave $slc_rlks $slc_alks
		cd $slc_dir/$slave
		echo " " >> $err_log
		echo "Coregistering "$slave" with "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
	    fi
	done < $slave_list
    else
	while read date; do
	    if [ ! -z $date ]; then
		slave=`echo $date | awk 'BEGIN {FS=","} ; {print $1}'`
 # SLC multi-look value
		echo "Coregistering "$slave" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks..."
		coregister_slave_SLC.bash $proj_dir/$proc_file $slave $slc_rlks $slc_alks
		cd $slc_dir/$slave
		echo " " >> $err_log
		echo "Coregistering "$slave" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
# ifm multi-look value
		echo " "
		echo "Coregistering "$slave" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks..."
		coregister_slave_SLC.bash $proj_dir/$proc_file $slave $ifm_rlks $ifm_alks
		cd $slc_dir/$slave
		echo " " >> $err_log
		echo "Coregistering "$slave" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks" >> $err_log
		less error.log >> $err_log		
	    fi
	done < $slave_list
    fi
    echo " "
    echo "Coregistering slave scenes to master scene completed."
    echo "   Run 'check_slave_coregistration.bash' script to check results before continuing processing."
    echo " "
elif [ $coregister == no -a $platform == GA ]; then
    echo " "
    echo "Option to coregister slaves to master scene not selected."
    echo " "
## NCI ##
elif [ $coregister == yes -a $platform == NCI ]; then
    cd $proj_dir/$track_dir/batch_scripts
    dem_jobid=`sed s/.r-man2// dem_job_id`
    # set up header for PBS job for slave list creation
    if [ -e $slave_list ]; then 
	rm -rf $slave_list
    fi
    slv=create_slave_list
    echo \#\!/bin/bash > $slv
    echo \#\PBS -lother=gdata1 >> $slv
    echo \#\PBS -l walltime=$slv_walltime >> $slv
    echo \#\PBS -l mem=$slv_mem >> $slv
    echo \#\PBS -l ncpus=$slv_ncpus >> $slv
    echo \#\PBS -l wd >> $slv
    echo \#\PBS -q normal >> $slv
    if [ $coregister_dem == yes ]; then
	echo \#\PBS -W depend=afterok:$dem_jobid >> $slv
    fi
    echo create_slaves_list.bash $proc_file >> $slv
    chmod +x $slv
    qsub $slv | tee slave_list_job_id

    slv_jobid=`sed s/.r-man2// slave_list_job_id`
    # set up header for PBS jobs for slave coregistration
    while read slave; do
	if [ ! -z $slave ]; then
	    if [ -e co_slc_$slave ]; then
		rm -rf co_slc_$slave
	    fi
	    co_slc=co_slc_$slave
	    echo \#\!/bin/bash > $co_slc
	    echo \#\PBS -lother=gdata1 >> $co_slc
	    echo \#\PBS -l walltime=$coreg_walltime >> $co_slc
	    echo \#\PBS -l mem=$coreg_mem >> $co_slc
	    echo \#\PBS -l ncpus=$coreg_ncpus >> $co_slc
	    echo \#\PBS -l wd >> $co_slc
	    echo \#\PBS -q normal >> $co_slc
	    echo \#\PBS -W depend=afterok:$slv_jobid >> $co_slc
	    echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/coregister_slave_SLC.bash $proc_file $slave >> $co_slc
	    chmod +x $co_slc
	    qsub $co_slc | tee co_slc_job_id
	else	
	    :
	fi
    done < $slave_list
else
    :
fi



##### PROCESS INTERFEROGRAMS AND GEOCODE UNWRAPPED FILES #####

## GA ##
if [ $do_ifms == yes -a $platform == GA ]; then
    echo "Creating interferograms..."
    echo " "
    while read list; do
	mas=`echo $list | awk 'BEGIN {FS=","} ; {print $1}'`
	slv=`echo $list | awk 'BEGIN {FS=","} ; {print $2}'`
	process_ifm.bash $proj_dir/$proc_file $mas $slv $ifm_rlks $ifm_alks
    done < $ifm_list
# consolidate ifm error logs into one file
    err_log=$err_dir/ifm_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_Interferogram_Error_Log" > $err_log
    echo " " >> $err_log
    echo " " >> $err_log
    while read ifm; do
	mas_slv_dir=$ifm_dir/$mas-$slv
	if [ ! -z $ifm ]; then
	    cd $mas_slv_dir
	    echo $mas-$slv >> $err_log
	    echo " " >> $err_log
	    less error.log >> $err_log
	fi
    done < $ifm_list
    echo " "
    echo "Processing interferograms complete."
    echo " "

# final baseline script
# plot_baseline_gamma.csh

elif [ $do_ifms == no -a $platform == GA ]; then
    echo " "
    echo "Option to create interferograms not selected."
    echo " "
## NCI ##
elif [ $do_ifms == yes -a $platform == NCI ]; then
    co_slc_jobid=`sed s/.r-man2// co_slc_job_id`
    cd $proj_dir/$track_dir/batch_scripts
    # set up header for PBS job for ifm list creation
    if [ -e $ifm_lists ]; then 
	rm -rf $ifm_lists
    fi
    ifm_lists=create_ifm_list
    echo \#\!/bin/bash > $ifm_lists
    echo \#\PBS -lother=gdata1 >> $ifm_lists
    echo \#\PBS -l walltime=$ifm_list_walltime >> $ifm_lists
    echo \#\PBS -l mem=$ifm_list_mem >> $ifm_lists
    echo \#\PBS -l ncpus=$ifm_list_ncpus >> $ifm_lists
    echo \#\PBS -l wd >> $ifm_lists
    echo \#\PBS -q normal >> $ifm_lists
    if [ $coregister == yes ]; then
	echo \#\PBS -W depend=afterok:$co_slc_jobid >> $ifm_lists
    fi
    echo create_ifms_list.bash $proc_file >> $ifm_lists
    chmod +x $ifm_lists
    qsub $ifm_lists | tee ifm_list_job_id

    ifm_list_jobid=`sed s/.r-man2// ifm_list_job_id`
    # set up header for PBS jobs for ifm creation
    
    if [ -e $ifm_list ]; then ## 190 or less ifms
	while read ifm_pair; do
	    if [ ! -z $ifm_pair ]; then
		mas=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $1}'`
		slv=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $2}'`
		mas_name=`echo $mas | awk '{print substr($1,3,6)}'`
		slv_name=`echo $slv | awk '{print substr($1,3,6)}'`
		ifm=ifm_$mas_name-$slv_name
		echo \#\!/bin/bash > $ifm
		echo \#\PBS -lother=gdata1 >> $ifm
		echo \#\PBS -l walltime=$ifm_walltime >> $ifm
		echo \#\PBS -l mem=$ifm_mem >> $ifm
		echo \#\PBS -l ncpus=$ifm_ncpus >> $ifm
		echo \#\PBS -l wd >> $ifm
		echo \#\PBS -q normal >> $ifm
		echo \#\PBS -W depend=afterok:$ifm_list_jobid >> $ifm
		echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $ifm
		chmod +x $ifm
		qsub $ifm
	    fi
	done < $ifm_list    	
    else ## more than 190 ifms (ifms list split into multiple lists)
	ifm_file_lists=$proj_dir/$track_dir/ifm_files.list
	
        # first list (relies on create ifm list to be run first, other lists rely of previous list to run first)
	first_list=`awk 'NR==1 {print $1}' $ifm_file_lists`
	while read list; do
	    if [ ! -z $list ]; then
		while read ifm_pair; do # create PBS jobs for each ifm in split ifm list
		    if [ ! -z $ifm_pair ]; then
			mas=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $1}'`
			slv=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $2}'`
			mas_name=`echo $mas | awk '{print substr($1,3,6)}'`
			slv_name=`echo $slv | awk '{print substr($1,3,6)}'`
			ifm=ifm_$mas_name-$slv_name
			echo \#\!/bin/bash > $ifm

			echo \#\PBS -l walltime=$ifm_walltime >> $ifm
			echo \#\PBS -l mem=$ifm_mem >> $ifm
			echo \#\PBS -l ncpus=$ifm_ncpus >> $ifm
			echo \#\PBS -l wd >> $ifm
			echo \#\PBS -q normal >> $ifm
			echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $ifm
			chmod +x $ifm
			paste $ifm > $first_list"_jobs_listing"
		    fi
		done < $list
                # create script to qsub each PBS job
		script=$first_list.bash 
		echo \#\!/bin/bash > $script
		echo "dir=$proj_dir/$track_dir/batch_scripts" >> $script
		echo "list="$first_list"_jobs_listing" >> $script
		echo "cd $dir" >> $script
		echo "while read job; do" >> $script
		echo "qsub $job" >> $script
		echo "done < $list" >> $script
		chmod +x $script
		# create PBS job to run script
		run_script=$first_list"_bulk"
		echo \#\!/bin/bash > $run_script

		echo \#\PBS -l walltime=00:30:00 >> $run_script
		echo \#\PBS -l mem=500MB >> $run_script
		echo \#\PBS -l ncpus=1 >> $run_script
		echo \#\PBS -l wd >> $run_script
		echo \#\PBS -q normal >> $run_script
		echo \#\PBS -W depend=afterok:$ifm_list_jobid >> $run_script
		echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $run_script
		chmod +x $run_script
		qsub $run_script | tee $run_script"_job_id"
	    fi
	done < $first_list

        # subsequent lists
	cp $ifm_file_lists ifm_files2.list
	tail -n +2 ifm_files2.list # remove first list
	remainder_list=ifm_files2.list

	while read list; do
	    if [ ! -z $list ]; then
		while read ifm_pair; do # create PBS jobs for each ifm in split ifm list
		    if [ ! -z $ifm_pair ]; then
			mas=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $1}'`
			slv=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $2}'`
			mas_name=`echo $mas | awk '{print substr($1,3,6)}'`
			slv_name=`echo $slv | awk '{print substr($1,3,6)}'`
			ifm=ifm_$mas_name-$slv_name
			echo \#\!/bin/bash > $ifm

			echo \#\PBS -l walltime=$ifm_walltime >> $ifm
			echo \#\PBS -l mem=$ifm_mem >> $ifm
			echo \#\PBS -l ncpus=$ifm_ncpus >> $ifm
			echo \#\PBS -l wd >> $ifm
			echo \#\PBS -q normal >> $ifm
			echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $ifm
			chmod +x $ifm
			paste $ifm > $list"_jobs_listing"
		    fi
		done < $list
                # create script to qsub each PBS job
		script=$first_list.bash 
		echo \#\!/bin/bash > $script
		echo "dir=$proj_dir/$track_dir/batch_scripts" >> $script
		echo "list="$first_list"_jobs_listing" >> $script
		echo "cd $dir" >> $script
		echo "while read job; do" >> $script
		echo "qsub $job" >> $script
		echo "done < $list" >> $script
		chmod +x $script
		# create PBS job to run script
		run_script=$first_list"_bulk"
		echo \#\!/bin/bash > $run_script

		echo \#\PBS -l walltime=00:30:00 >> $run_script
		echo \#\PBS -l mem=500MB >> $run_script
		echo \#\PBS -l ncpus=1 >> $run_script
		echo \#\PBS -l wd >> $run_script
		echo \#\PBS -q normal >> $run_script
		echo \#\PBS -W depend=afterok:$_list_jobid >> $run_script
		echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $run_script
		chmod +x $run_script
		qsub $run_script | tee $run_script"_job_id"
	    fi
	done < $remainder_list

    fi
	geocode_nci.csh {$mas}-{$slv}_{$polar}_{$ifm_looks}rlks.unw $proj_dir/$proc_file - 1 -

else
    :
fi



##### ADD NEW SLCS TO EXISTING SLC COLLECTION #####

## GA ##
if [ $add_slc == yes -a $platform == GA ]; then
# extract raw data
    cd $raw_dir_ga
    echo "Extracting raw data for additional SLC data..."
    echo " "
    mkdir -p date_dirs
    while read scene; do
	tar=`echo $scene*.gz`
	if [ ! -z $scene ]; then
	    if [ ! -d $raw_dir_ga/date_dirs/$scene ]; then #check if data have already been extracted from tar file
		tar -xvzf $tar
		mv $scene date_dirs
	    else
		echo "Raw data already extracted for" $scene"."
	    fi
	else
	    :
	fi
    done < $add_scene_list
# create SLC data
# consolidate error logs into one file
    err_log=$err_dir/SLC_add_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_Additional_SLC_Creation_Error_Log" > $err_log
    echo " " >> $err_log
    echo " "
    echo "Creating additional SLC data..."
    echo " "
# SLC and ifm multi-look value (same value)
    if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	while read scene; do
	    if [ ! -z $scene ]; then
		echo "Creating SLC for "$scene" with "$slc_rlks" range and "$slc_alks" azimuth looks..."
		process_$sensor"_SLC.bash" $proj_dir/$proc_file $scene $slc_rlks $slc_alks
		cd $slc_dir/$scene
		echo " " >> $err_log
		echo "Creating SLC for "$scene" with "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
	    else
		:
	    fi
	done < $add_scene_list
    else
	while read scene; do
	    if [ ! -z $scene ]; then
 # SLC multi-look value
		echo "Creating SLC for "$scene" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks..."
		process_$sensor"_SLC.bash" $proj_dir/$proc_file $scene $slc_rlks $slc_alks
		cd $slc_dir/$scene
		echo " " >> $err_log
		echo "Creating SLC for "$scene" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
# ifm multi-look value
		echo "Creating SLC for "$scene" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks..."
		process_$sensor"_SLC.bash" $proj_dir/$proc_file $scene $ifm_rlks $ifm_alks
		cd $slc_dir/$scene
		echo " " >> $err_log
		echo "Creating SLC for "$scene" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
	    else
		:
	    fi
	done < $add_scene_list
    fi
    echo " "
    echo "Processing additional SLCs completed."
    echo " "
elif [ $do_slc == no -a $platform == GA ]; then
    echo " "
    echo "Option to create additional SLC data not selected."
    echo " "
## NCI ##
elif [ $do_slc == yes -a $platform == NCI ]; then
# extract raw data from MDSS
    cd $proj_dir/$track_dir/batch_scripts
    raw=extract_raw # nci script to extract raw data
    echo \#\!/bin/bash > $raw
    echo \#\PBS -lother=gdata1 >> $raw
    echo \#\PBS -l walltime=$raw_walltime >> $raw
    echo \#\PBS -l mem=$raw_mem >> $raw
    echo \#\PBS -l ncpus=$raw_ncpus >> $raw
    echo \#\PBS -l wd >> $raw
    echo \#\PBS -q copyq >> $raw
    echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/extract_nci_raw_data.bash $proc_file >> $raw
    chmod +x $raw
    qsub $raw 
# create SLC data
    cd $proj_dir/$track_dir/batch_scripts
# set up and submit PBS job script for each SLC
    while read scene; do
	if [ ! -z $scene ]; then
	    slc_script=slc_$scene
	    rm -rf $slc_script
	    echo \#\!/bin/bash > $slc_script
	    echo \#\PBS -lother=gdata1 >> $slc_script
	    echo \#\PBS -l walltime=$slc_walltime >> $slc_script
	    echo \#\PBS -l mem=$slc_mem >> $slc_script
	    echo \#\PBS -l ncpus=$slc_ncpus >> $slc_script
	    echo \#\PBS -l wd >> $slc_script
	    echo \#\PBS -q normal >> $slc_script    
	    echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/"process_"$sensor"_SLC.bash" $proc_file $scene >> $slc_script
	    chmod +x $slc_script
            qsub $slc_script | tee slc_job_id
	fi
    done < $scene_list
    slc_jobid=`sed s/.r-man2// slc_job_id`
    slc_errors=slc_error_check
    rm -rf $slc_errors
    echo \#\!/bin/bash > $slc_errors
    echo \#\PBS -lother=gdata1 >> $slc_errors
    echo \#\PBS -l walltime=00:15:00 >> $slc_errors
    echo \#\PBS -l mem=500MB >> $slc_errors
    echo \#\PBS -l ncpus=1 >> $slc_errors
    echo \#\PBS -l wd >> $slc_errors
    echo \#\PBS -q normal >> $slc_errors
    echo \#\PBS -W depend=afterok:$slc_jobid >> $slc_errors
    echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/collate_errors_slc.bash $proc_file >> $slc_errors
    chmod +x $slc_errors
    qsub $slc_errors | tee slc_errors_job_id
else
    :
fi

##### COREGISTER ADDITIONAL SLAVE SCENES TO MASTER SCENE #####


## GA ##
if [ $coregister_add == yes -a $platform == GA ]; then
    cd $proj_dir/$track_dir
    cp add_scenes.list add_slaves.list
    cd $proj_dir
# consolidate error logs into one file
    err_log=$err_dir/SLC_add_coreg_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_Coregister_Additional_SLC_Error_Log" > $err_log
    echo " " >> $err_log
    echo "Coregistering additional slave scenes to master scene..."
# SLC and ifm multi-look value (same value)
    if [ $slc_rlks -eq $ifm_rlks -a $slc_alks -eq $ifm_alks ]; then
	while read date; do
	    if [ ! -z $date ]; then
		slave=`echo $date | awk 'BEGIN {FS=","} ; {print $1}'`
		echo "Coregistering "$slave" to master scene with "$slc_rlks" range and "$slc_alks" azimuth looks..."
		coregister_slave_SLC.bash $proj_dir/$proc_file $slave $slc_rlks $slc_alks
		cd $slc_dir/$slave
		echo " " >> $err_log
		echo "Coregistering "$slave" with "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
	    fi
	done < $add_slave_list
    else
	while read date; do
	    if [ ! -z $date ]; then
		slave=`echo $date | awk 'BEGIN {FS=","} ; {print $1}'`
 # SLC multi-look value
		echo "Coregistering "$slave" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks..."
		coregister_slave_SLC.bash $proj_dir/$proc_file $slave $slc_rlks $slc_alks
		cd $slc_dir/$slave
		echo " " >> $err_log
		echo "Coregistering "$slave" with SLC "$slc_rlks" range and "$slc_alks" azimuth looks" >> $err_log
		less error.log >> $err_log
# ifm multi-look value
		echo "Coregistering "$slave" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks..."
		coregister_slave_SLC.bash $proj_dir/$proc_file $slave $ifm_rlks $ifm_alks
		cd $slc_dir/$slave
		echo " " >> $err_log
		echo "Coregistering "$slave" with ifm "$ifm_rlks" range and "$ifm_alks" azimuth looks" >> $err_log
		less error.log >> $err_log		
	    fi
	done < $add_slave_list
    fi
    echo " "
    echo "Coregister additional slave scenes to master scene completed."
    echo "   Run 'check_slave_coregistration.bash' script to check results before continuing processing."
    echo " "
elif [ $coregister_add == no -a $platform == GA ]; then
    echo " "
    echo "Option to coregister additional slaves to master scene not selected."
    echo " "
## NCI ##
elif [ $coregister_add == yes -a $platform == NCI ]; then
    cd $proj_dir/$track_dir/batch_scripts
    dem_jobid=`sed s/.r-man2// dem_job_id`
    # set up header for PBS job for slave list creation
    if [ -e $slave_list ]; then 
	rm -rf $slave_list
    fi
    slv=create_slave_list
    echo \#\!/bin/bash > $slv
    echo \#\PBS -lother=gdata1 >> $slv
    echo \#\PBS -l walltime=$slv_walltime >> $slv
    echo \#\PBS -l mem=$slv_mem >> $slv
    echo \#\PBS -l ncpus=$slv_ncpus >> $slv
    echo \#\PBS -l wd >> $slv
    echo \#\PBS -q normal >> $slv
    if [ $coregister_dem == yes ]; then
	echo \#\PBS -W depend=afterok:$dem_jobid >> $slv
    fi
    echo create_slaves_list.bash $proc_file >> $slv
    chmod +x $slv
    qsub $slv | tee slave_list_job_id

    slv_jobid=`sed s/.r-man2// slave_list_job_id`
    # set up header for PBS jobs for slave coregistration
    while read slave; do
	if [ ! -z $slave ]; then
	    if [ -e co_slc_$slave ]; then
		rm -rf co_slc_$slave
	    fi
	    co_slc=co_slc_$slave
	    echo \#\!/bin/bash > $co_slc
	    echo \#\PBS -lother=gdata1 >> $co_slc
	    echo \#\PBS -l walltime=$coreg_walltime >> $co_slc
	    echo \#\PBS -l mem=$coreg_mem >> $co_slc
	    echo \#\PBS -l ncpus=$coreg_ncpus >> $co_slc
	    echo \#\PBS -l wd >> $co_slc
	    echo \#\PBS -q normal >> $co_slc
	    echo \#\PBS -W depend=afterok:$slv_jobid >> $co_slc
	    echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/coregister_slave_SLC.bash $proc_file $slave >> $co_slc
	    chmod +x $co_slc
	    qsub $co_slc | tee co_slc_job_id
	else	
	    :
	fi
    done < $slave_list
else
    :
fi



##### PROCESS ADDITIONAL INTERFEROGRAMS AND GEOCODE UNWRAPPED FILES #####

## GA ##
if [ $do_add_ifms == yes -a $platform == GA ]; then
# create updated scenes and ifms.list file
    echo "Creating updated scene and interferogram list files..."
    create_ifms_list.bash $proj_dir/$proc_file
    echo "Creating interferograms..."
    echo " "
    while read list; do
	mas=`echo $list | awk 'BEGIN {FS=","} ; {print $1}'`
	slv=`echo $list | awk 'BEGIN {FS=","} ; {print $2}'`
	process_ifm.bash $proj_dir/$proc_file $mas $slv $ifm_rlks $ifm_alks
    done < $add_ifm_list
# consolidate ifm error logs into one file
    err_log=$err_dir/ifm_add_error.log
    echo "PROJECT: "$project"_"$sensor"_"$track_dir"_Additional_Interferogram_Error_Log" > $err_log
    echo " " >> $err_log
    echo " " >> $err_log
    while read ifm; do
	mas_slv_dir=$ifm_dir/$mas-$slv
	if [ ! -z $ifm ]; then
	    cd $mas_slv_dir
	    echo $mas-$slv >> $err_log
	    echo " " >> $err_log
	    less error.log >> $err_log
	fi
    done < $add_ifm_list
    echo " "
    echo "Processing additional interferograms complete."
    echo " "

# updated final baseline script
# plot_baseline_gamma.csh

elif [ $do_add_ifms == no -a $platform == GA ]; then
    echo " "
    echo "Option to create additional interferograms not selected."
    echo " "
## NCI ##
elif [ $do_add_ifms == yes -a $platform == NCI ]; then
    co_slc_jobid=`sed s/.r-man2// co_slc_job_id`
    cd $proj_dir/$track_dir/batch_scripts
    # set up header for PBS job for ifm list creation
    if [ -e $ifm_lists ]; then 
	rm -rf $ifm_lists
    fi
    ifm_lists=create_ifm_list
    echo \#\!/bin/bash > $ifm_lists
    echo \#\PBS -lother=gdata1 >> $ifm_lists
    echo \#\PBS -l walltime=$ifm_list_walltime >> $ifm_lists
    echo \#\PBS -l mem=$ifm_list_mem >> $ifm_lists
    echo \#\PBS -l ncpus=$ifm_list_ncpus >> $ifm_lists
    echo \#\PBS -l wd >> $ifm_lists
    echo \#\PBS -q normal >> $ifm_lists
    if [ $coregister == yes ]; then
	echo \#\PBS -W depend=afterok:$co_slc_jobid >> $ifm_lists
    fi
    echo create_ifms_list.bash $proc_file >> $ifm_lists
    chmod +x $ifm_lists
    qsub $ifm_lists | tee ifm_list_job_id

    ifm_list_jobid=`sed s/.r-man2// ifm_list_job_id`
    # set up header for PBS jobs for ifm creation
    
    if [ -e $ifm_list ]; then ## 190 or less ifms
	while read ifm_pair; do
	    if [ ! -z $ifm_pair ]; then
		mas=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $1}'`
		slv=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $2}'`
		mas_name=`echo $mas | awk '{print substr($1,3,6)}'`
		slv_name=`echo $slv | awk '{print substr($1,3,6)}'`
		ifm=ifm_$mas_name-$slv_name
		echo \#\!/bin/bash > $ifm
		echo \#\PBS -lother=gdata1 >> $ifm
		echo \#\PBS -l walltime=$ifm_walltime >> $ifm
		echo \#\PBS -l mem=$ifm_mem >> $ifm
		echo \#\PBS -l ncpus=$ifm_ncpus >> $ifm
		echo \#\PBS -l wd >> $ifm
		echo \#\PBS -q normal >> $ifm
		echo \#\PBS -W depend=afterok:$ifm_list_jobid >> $ifm
		echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $ifm
		chmod +x $ifm
		qsub $ifm
	    fi
	done < $ifm_list    	
    else ## more than 190 ifms (ifms list split into multiple lists)
	ifm_file_lists=$proj_dir/$track_dir/ifm_files.list
	
        # first list (relies on create ifm list to be run first, other lists rely of previous list to run first)
	first_list=`awk 'NR==1 {print $1}' $ifm_file_lists`
	while read list; do
	    if [ ! -z $list ]; then
		while read ifm_pair; do # create PBS jobs for each ifm in split ifm list
		    if [ ! -z $ifm_pair ]; then
			mas=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $1}'`
			slv=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $2}'`
			mas_name=`echo $mas | awk '{print substr($1,3,6)}'`
			slv_name=`echo $slv | awk '{print substr($1,3,6)}'`
			ifm=ifm_$mas_name-$slv_name
			echo \#\!/bin/bash > $ifm

			echo \#\PBS -l walltime=$ifm_walltime >> $ifm
			echo \#\PBS -l mem=$ifm_mem >> $ifm
			echo \#\PBS -l ncpus=$ifm_ncpus >> $ifm
			echo \#\PBS -l wd >> $ifm
			echo \#\PBS -q normal >> $ifm
			echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $ifm
			chmod +x $ifm
			paste $ifm > $first_list"_jobs_listing"
		    fi
		done < $list
                # create script to qsub each PBS job
		script=$first_list.bash 
		echo \#\!/bin/bash > $script
		echo "dir=$proj_dir/$track_dir/batch_scripts" >> $script
		echo "list="$first_list"_jobs_listing" >> $script
		echo "cd $dir" >> $script
		echo "while read job; do" >> $script
		echo "qsub $job" >> $script
		echo "done < $list" >> $script
		chmod +x $script
		# create PBS job to run script
		run_script=$first_list"_bulk"
		echo \#\!/bin/bash > $run_script

		echo \#\PBS -l walltime=00:30:00 >> $run_script
		echo \#\PBS -l mem=500MB >> $run_script
		echo \#\PBS -l ncpus=1 >> $run_script
		echo \#\PBS -l wd >> $run_script
		echo \#\PBS -q normal >> $run_script
		echo \#\PBS -W depend=afterok:$ifm_list_jobid >> $run_script
		echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $run_script
		chmod +x $run_script
		qsub $run_script | tee $run_script"_job_id"
	    fi
	done < $first_list

        # subsequent lists
	cp $ifm_file_lists ifm_files2.list
	tail -n +2 ifm_files2.list # remove first list
	remainder_list=ifm_files2.list

	while read list; do
	    if [ ! -z $list ]; then
		while read ifm_pair; do # create PBS jobs for each ifm in split ifm list
		    if [ ! -z $ifm_pair ]; then
			mas=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $1}'`
			slv=`echo $ifm_pair | awk 'BEGIN {FS=","} ; {print $2}'`
			mas_name=`echo $mas | awk '{print substr($1,3,6)}'`
			slv_name=`echo $slv | awk '{print substr($1,3,6)}'`
			ifm=ifm_$mas_name-$slv_name
			echo \#\!/bin/bash > $ifm

			echo \#\PBS -l walltime=$ifm_walltime >> $ifm
			echo \#\PBS -l mem=$ifm_mem >> $ifm
			echo \#\PBS -l ncpus=$ifm_ncpus >> $ifm
			echo \#\PBS -l wd >> $ifm
			echo \#\PBS -q normal >> $ifm
			echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $ifm
			chmod +x $ifm
			paste $ifm > $list"_jobs_listing"
		    fi
		done < $list
                # create script to qsub each PBS job
		script=$first_list.bash 
		echo \#\!/bin/bash > $script
		echo "dir=$proj_dir/$track_dir/batch_scripts" >> $script
		echo "list="$first_list"_jobs_listing" >> $script
		echo "cd $dir" >> $script
		echo "while read job; do" >> $script
		echo "qsub $job" >> $script
		echo "done < $list" >> $script
		chmod +x $script
		# create PBS job to run script
		run_script=$first_list"_bulk"
		echo \#\!/bin/bash > $run_script

		echo \#\PBS -l walltime=00:30:00 >> $run_script
		echo \#\PBS -l mem=500MB >> $run_script
		echo \#\PBS -l ncpus=1 >> $run_script
		echo \#\PBS -l wd >> $run_script
		echo \#\PBS -q normal >> $run_script
		echo \#\PBS -W depend=afterok:$_list_jobid >> $run_script
		echo /home/547/mcg547/dg9-apps/GAMMA/gamma_scripts/process_ifm.bash $proc_file $mas $slv >> $run_script
		chmod +x $run_script
		qsub $run_script | tee $run_script"_job_id"
	    fi
	done < $remainder_list

    fi
	geocode_nci.csh {$mas}-{$slv}_{$polar}_{$ifm_looks}rlks.unw $proj_dir/$proc_file - 1 -

else
    :
fi


##### RE-COREGISTER DEM WITH MODIFIED MULTI-LOOK VALUE #####

#recoregister_dem=`grep Re-coregister_DEM= $proc_file | cut -d "=" -f 2`




##### RE-COREGISTER SLAVE SCENES TO MASTER SCENE WITH MODIFIED MULTI-LOOK VALUE #####

#recoregister_dem=`grep Re-coregister_DEM= $proc_file | cut -d "=" -f 2`




##### RE-PROCESS INTERFEROGRAMS WITH MODIFIED MULTI-LOOK VALUE #####

#recoregister_dem=`grep Re-coregister_DEM= $proc_file | cut -d "=" -f 2`




##### CLEAN UP FILES #####






# script end 
####################

## Copy errors to NCI error file (.e file)
#if [ $platform == NCI ]; then
#   cat error.log 1>&2
#   rm temp_log
#else
#   :
#fi
