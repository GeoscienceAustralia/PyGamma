#!/bin/bash

display_usage() {
    echo ""
    echo "*******************************************************************************"
    echo "* extract_raw_data: Script extracts and untars raw data files from the MDSS   *"
    echo "*                   or Sentinel-1 archive (NCI) and puts them into the        *"
    echo "*                   'raw_data' directory for GAMMA processing.                *"
    echo "*                                                                             *"
    echo "* input:  [proc_file]    name of GAMMA proc file (eg. gamma.proc)             *"
    echo "*         [scene]        scene ID (eg. 20180423)                              *"
    echo "*         <S1_grid_dir>  S1 grid directory name                               *"
    echo "*         <S1_zip_file>  S1 zip file name                                     *"
    echo "*         <S1_frame_number>     S1 frame number                               *"
    echo "*                                                                             *"
    echo "* author: Sarah Lawrie @ GA       01/05/2015, v1.0                            *"
    echo "*         Sarah Lawrie @ GA       18/06/2015, v1.1                            *"
    echo "*             - streamline auto processing and modify directory structure     *"
    echo "*         Sarah Lawrie @ GA       29/01/2016, v1.2                            *"
    echo "*             - add ability to extract S1 data from the RDSI                  *"
    echo "*         Sarah Lawrie @ GA       08/09/2017, v1.3                            *"
    echo "*             - update paths to S1 data and auto create frame dirs for S1     *"
    echo "*         Sarah Lawrie @ GA       13/08/2018, v2.0                            *"
    echo "*             -  Major update to streamline processing:                       *"
    echo "*                  - use functions for variables and PBS job generation       *"
    echo "*                  - add option to auto calculate multi-look values and       *"
    echo "*                      master reference scene                                 *"
    echo "*                  - add initial and precision baseline calculations          *"
    echo "*                  - add full Sentinel-1 processing, including resizing and   *"
    echo "*                     subsetting by bursts                                    *"
    echo "*                  - remove GA processing option                              *"
    echo "*         Sarah Lawrie @ GA       12/09/2018, v2.1                            *"
    echo "*                  - refine zip download to only include files related to     *"
    echo "*                    polarisation rather than full zip file                   *"
    echo "*******************************************************************************"
    echo -e "Usage: extract_raw_data.bash [proc_file] [scene] <S1_grid_dir> <S1_zip_file> <S1_frame_number>"
    }

if [ $# -lt 2 ]
then
    display_usage
    exit 1
fi

proc_file=$1
scene=$2
grid=$3
zip=$4
frame_num=$5

# extract_raw_data.bash /g/data1/dg9/INSAR_ANALYSIS/NT_EQ_MAY2016/S1/GAMMA/T075D.proc 20151017 25S130E-30S135E S1A_IW_SLC__1SDV_20151017T204339_20151017T204406_008197_00B871_9B84.zip 1 -



##########################   GENERIC SETUP  ##########################

# Load generic GAMMA functions
source ~/repo/gamma_insar/gamma_functions

# Load variables and directory paths
proc_variables $proc_file
final_file_loc

# Load GAMMA to access GAMMA programs
source $config_file

# Print processing summary to .o & .e files
PBS_processing_details $project $track $scene 

######################################################################


cd $raw_data_track_dir


## Create list of scenes
if [ $sensor != 'S1' ]; then #non Sentinel-1
    if [ -f $frame_list ]; then # if frames exist
	while read frame; do
	    if [ ! -z $frame ]; then # skips any empty lines
		tar=$scene"_"$sensor"_"$track"_F"$frame.tar.gz
		if [ ! -z $tar ]; then
		    if [ -d $raw_data_track_dir/F$frame/$scene ]; then #check if data have already been extracted from tar file
			:
		    else #data on MDSS
			mdss get $mdss_data_dir/F$frame/$tar < /dev/null $raw_data_track_dir/F$frame # /dev/null allows mdss command to work properly in loop
			cd $raw_data_track_dir/F$frame
			tar -xvzf $tar
			rm -rf $tar
		    fi
		else
		    :
		fi
	    fi
	done < $frame_list
    else # no frames exist
	tar=$scene"_"$sensor"_"$track.tar.gz
	if [ ! -z $tar ]; then
	    if [ -d $raw_data_track_dir/$scene ]; then #check if data have already been extracted from tar file
	   	:
	    else
		mdss get $mdss_data_dir/$tar < /dev/null $raw_data_track_dir # /dev/null allows mdss command to work properly in loop
		cd $raw_data_track_dir
		tar -xvzf $tar
		rm -rf $tar
	    fi
	else
	    :
	fi
    fi
else # Sentinel-1 
    year=`echo $scene | awk '{print substr($1,1,4)}'`
    month=`echo $scene | awk '{print substr($1,5,2)}'`
    s1_type=`echo $zip | cut -d "_" -f 1`

    # create scene directories
    cd $raw_data_track_dir/F$frame_num
    if [ -f $scene ]; then
	: # data already extracted
    else
	mkdir -p $scene
	cd $scene
	
	# change polarisation variable to lowercase
	pol=`echo $polar | tr '[:upper:]' '[:lower:]'`

	# copy relevant parts of zip file 
	dir_name=`basename $zip | cut -d "." -f 1`
	dir=$dir_name.SAFE
	anno_dir=$dir/annotation
	meas_dir=$dir/measurement
	cal_noise_dir=$anno_dir/calibration
	zip_loc=$s1_path/$year/$year-$month/$grid/$zip
	#mkdir -p $dir

	# extract manifest.safe file
	unzip -j $zip_loc $dir/manifest.safe -d $dir

	# extract files based on polarisation
	unzip -l $zip_loc | grep -E 'annotation/s1' | awk '{print $4}' | cut -d "/" -f 3 | sed -n '/'-"$pol"-'/p' > xml_list
	unzip -l $zip_loc | grep -E 'measurement/s1' | awk '{print $4}' | cut -d "/" -f 3 | sed -n '/'-"$pol"-'/p' > data_list
	unzip -l $zip_loc | grep -E 'calibration/calibration-s1' | awk '{print $4}' | cut -d "/" -f 4 | sed -n '/'-"$pol"-'/p' > calib_list
	unzip -l $zip_loc | grep -E 'calibration/noise-s1' | awk '{print $4}' | cut -d "/" -f 4 | sed -n '/'-"$pol"-'/p' > noise_list
	while read xml; do
	    unzip -j $zip_loc $anno_dir/$xml -d $anno_dir
	done < xml_list
	rm -f xml_list
	while read data; do
	    unzip -j $zip_loc $meas_dir/$data -d $meas_dir
	done < data_list
	rm -f data_list
	while read calib; do
	    unzip -j $zip_loc $cal_noise_dir/$calib -d $cal_noise_dir
	done < calib_list
	rm -f calib_list
	while read noise; do
	    unzip -j $zip_loc $cal_noise_dir/$noise -d $cal_noise_dir
	done < noise_list
	rm -f noise_list

	# get precision orbit file
	start_date=`date -d "$scene -1 days" +%Y%m%d`
	stop_date=`date -d "$scene +1 days" +%Y%m%d`
	# check if orbit files are missing are missing
	if [ $s1_type == "S1A" ]; then
	    if grep -R "$scene" $s1_orbits/missing_S1A; then
		echo "No orbit file available for date: "$scene
	    else
		cp $s1_orbits/$s1_type/*V$start_date*_$stop_date*.EOF .
	    fi
	elif [ $s1_type == "S1B" ]; then
	    if grep -R "$scene" $s1_orbits/missing_S1B; then
		echo "No orbit file available for date: "$scene
	    else
		cp $s1_orbits/$s1_type/*V$start_date*_$stop_date*.EOF .
	    fi
	fi
	cd $proj_dir
    fi
fi
# script end
####################

