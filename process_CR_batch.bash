#!/bin/bash

display_usage() {
    echo ""
    echo "*******************************************************************************"
    echo "* process_CR_batch: Scripts fruns process_CR.bash as a batch process using    *"
    echo "*                   a list of scenes and list of CR sites.                    *"
    echo "*                                                                             *"
    echo "*                   Format for list of scenes:                                *"
    echo "*                       yyyymmdd                                              *"
    echo "*                                                                             *"
    echo "* input:  [proc_file]  name of GAMMA proc file (eg. gamma.proc)               *"
    echo "*         [list]       list of scenes                                         *"
    echo "*         [cr_file]    full path to ASCII file of CR locations and centre of  *"
    echo "*                      clutter window                                         *"
    echo "*                                                                             *"
    echo "* author: Sarah Lawrie @ GA       20/04/2015, v1.0                            *"
    echo "*******************************************************************************"
    echo -e "Usage: process_CR.bash [proc_file] [list] [cr_file]"
    }

if [ $# -lt 3 ]
then 
    display_usage
    exit 1
fi

proc_file=$1

## Variables from parameter file (*.proc)
platform=`grep Platform= $proc_file | cut -d "=" -f 2`
project=`grep Project= $proc_file | cut -d "=" -f 2`
track_dir=`grep Track= $proc_file | cut -d "=" -f 2`
polar=`grep Polarisation= $proc_file | cut -d "=" -f 2`
sensor=`grep Sensor= $proc_file | cut -d "=" -f 2`
slc_looks=`grep SLC_multi_lookr= $proc_file | cut -d "=" -f 2`

list=$2
cr_file=$3

## Identify project directory based on platform
if [ $platform == NCI ]; then
    proj_dir=/g/data1/dg9/INSAR_ANALYSIS/$project
else
    proj_dir=/nas/gemd/insar/INSAR_ANALYSIS/$project/$sensor/GAMMA
fi

## Load GAMMA based on platform
if [ $platform == NCI ]; then
    GAMMA=`grep GAMMA_NCI= $proc_file | cut -d "=" -f 2`
    source $GAMMA
else
    GAMMA=`grep GAMMA_GA= $proc_file | cut -d "=" -f 2`
    source $GAMMA
fi

slc_dir=$proj_dir/$track_dir/`grep SLC_dir= $proc_file | cut -d "=" -f 2`
cr_dir=$proj_dir/$track_dir/`grep CR_dir= $proc_file | cut -d "=" -f 2`

while read scene; do
    date=`echo $scene | awk '{print $1}'`
    scene_dir=$cr_dir/$date
    date_dir=$slc_dir/$date
    name=$date"_"$polar
    outfile=$scene_dir/$date"_CR_RCS_summary.txt"
    slc=$date_dir/r$name.slc
    slc_par=$slc.par

    cd $proj_dir

    mkdir -p $cr_dir
    mkdir -p $cr_dir/$date

    if [ $sensor == "S1" ]; then
	flag=1
    else
	flag=0
    fi

    echo "Site CR_ID Total_Energy Avg_Clutter Total_Clutter Total_Energy_minus_Clutter SCR Phase_Error_metres CR_RCS pwin inc" >! $outfile

    while read site; do
        #cr=`echo $line | awk -F'\t' '{print $1}'`
        #site=`awk '$1=="'"$line"'" {print $1}' $crfile`
	cr=`awk '$1=="'"$site"'" {print $2}' $crfile`
	rg_loc=`awk '$1=="'"$site"'" {print $3}' $crfile`
	az_loc=`awk '$1=="'"$site"'" {print $4}' $crfile`
        #clt_rg=`awk '$1=="'"$site"'" {print $5}' $crfile`
        #clt_az=`awk '$1=="'"$site"'" {print $6}' $crfile`
	pwin=`awk '$1=="'"$site"'" {print $7}' $crfile`
	cwin=`awk '$1=="'"$site"'" {print $8}' $crfile`
	cross_width=`awk '$1=="'"$site"'" {print $9}' $crfile`
	cr_rcs=`awk '$1=="'"$site"'" {print $10}' $crfile`

	echo $slc $site $cr $rg_loc $az_loc $pwin $cwin $cross_width $cr_rcs
	process_CR.bash $proc_file $slc $date $site $cr $rg_loc $az_loc $pwin $cwin $cross_width $cr_rcs $flag

	tail -1 $scene_dir/$date"_"$site"_CR_"$cr.txt >> $outfile

    done < awk 'NR>1 {print $1}' $crfile

done < $list





















scene_dir=$CR_dir/$date

cd $proj_dir

mkdir -p $CR_dir
mkdir -p $CR_dir/$date

cd $scene_dir

width=`grep range_samples $slc_par | awk '{print $2}'`

echo "1,1" > quad.txt
echo "1,-1" >> quad.txt
echo "-1,-1" >> quad.txt
echo "-1,1" >> quad.txt

osf=16

# extract average clutter in four quadrants surrounding point target response

#half cross width
cr_off=`echo $cross_width | awk '{printf "%.0f\n", $1/2+0.01}'`
#clutter region window size
cwinm=`echo $cwin $cr_off | awk '{print ($1/2)-$2}'`
# number of clutter samples in 4 quadrants
nclt=`echo $cwinm | awk '{print 4*$1*$1}'`
nsamp=`echo $pwin | awk '{print $1*$1}'`
#clutter region centre offset
cwin_off=`echo $cwinm $cr_off | awk '{printf "%.0f\n", ($1/2)+$2}'`

echo "cr_off cwin nclt nsamp cwin_off"
echo $cr_off $cwinm $nclt $nsamp $cwin_off

rm -f clutter.txt

while read line; do
    rg_pol=`echo $line | sed 's/,/ /g' | awk '{print $1}'`
    az_pol=`echo $line | sed 's/,/ /g' | awk '{print $2}'`
    clt_rg=`echo $rg_loc $rg_pol $cwin_off | awk '{print $1+($2*$3)}'`
    clt_az=`echo $az_loc $az_pol $cwin_off | awk '{print $1+($2*$3)}'`
    echo "clt_rg clt_az rg_pol az_pol"
    echo $clt_rg $clt_az $rg_pol $az_pol

    # extract average clutter for clutter region
    if [ $flag -eq  0 ]; then
	ptarg_cal_SLC $slc_par $slc $rg_loc $az_loc $cr_rcs $clt_rg $clt_az blah1 blah2 blah3 blah4 $osf 4 0 $pwin $cwinm >! temp.txt
    elif [ $flag -eq 1 ]; then 
	ptarg_cal_MLI $slc_par $slc $rg_loc $az_loc $cr_rcs $clt_rg $clt_az blah1 blah2 blah3 blah4 $osf 4 0 $pwin $cwinm >! temp.txt
    else
	:
    fi
    grep "average clutter intensity per sample" temp.txt | awk '{print $6}' >> clutter.txt
    rm -f temp.txt
done < quad.txt

sum_avg_clt=`awk '{ SUM += $1 } END {printf "%.10e\n", SUM/4}' clutter.txt`
rm -f blah1 blah2 blah3 blah4 clutter.txt

# NEEDED for 'ptarg' but not 'ptarg_cal_SLC'
format=`grep image_format $slc_par | awk '{print $2}'`
if [ $format == "FCOMPLEX" ]; then
    fflag=0
elif [ $format == "SCOMPLEX" ]; then
    fflag=1
elif [ $format == "FLOAT" ]; then
    fflag=2
else
    :
fi

#echo $date $site $cr $rg_loc $az_loc $clt_rg $clt_az

# Use unit RCS for psigma in order to evaluate CR RCS in image rather than determine calibration factor
if [ $flag -eq 0 ]; then
    ptarg_cal_SLC $slc_par $slc $rg_loc $az_loc $cr_rcs $clt_rg $clt_az $stub.mph $stub"_rg.txt" $stub"_az.txt" $stub"_pcal.txt" $osf 4 0 $pwin 8 >! $stub.txt
    inc=1
elif [ $flag -eq 1 ]; then
    ptarg_cal_MLI $slc_par $slc $rg_loc $az_loc $cr_rcs $clt_rg $clt_az $stub.mph $stub"_rg.txt" $stub"_az.txt" $stub"_pcal.txt" $osf 4 0 $pwin 8 >! $stub.txt
    inc=`grep incidence $stub.txt | awk '{print sin($7*(4*atan2(1,1))/180)}'`
else
    :
fi

#sum_avg_clt=`echo $temp_clt $inc | awk '{printf "%.10e\n", $1*$2}'`
#inferred total clutter energy in target window
total_clt=`echo $sum_avg_clt $pwin | awk '{printf "%.10e\n", $1*$2*$2}'`
# actual total energy in target window
total_E=`grep "calibration target energy including clutter:" $stub.txt | awk '{printf "%.10e\n", $6}'`
# actual total energy minus inferred total clutter
total_E_minus_clt=`echo $total_E $total_clt | awk '{printf "%.10e\n", $1-$2}'`
# ratio of integrated target Energy and average energy per pixel over all four clutter windows
scr=`echo $total_E_minus_clt $sum_avg_clt | awk '{printf "%.10e\n", $1/$2}'`
#avg_clt=`grep "average clutter intensity per sample" $stub.txt | awk '{print $6}'`
#rcs=`grep assuming $stub.txt | awk '{print $11}'`

pix_area=`grep "pixel area ellipsoid" $stub.txt | awk '{printf "%.10e\n", $5}'`
#scr=`grep average_clutter $stub.txt | awk '{printf "%g\n", $6}'`
rcs=`echo $pix_area $total_E_minus_clt $inc | awk '{printf "%.10e\n", $1*$2*$3}'`
echo $pix_area $total_E_minus_clt
wvl=`grep radar_frequency $slc_par | awk '{print 300000000/$2}'`
# Phase error based on Adam 2004, Kampes 2006 and Ketelaar 2004
ph_err=`echo $scr $wvl | awk '{print ($2/4*atan2(0, -1))*(1/(sqrt(2*$1)))}'`

# ptarg_cal_SLC works on beta0 SLC. Convert the output to sigma0 equivalent by multiplying by sin(inc_ang)
#echo $site $cr $scr $rcs $inc $avg_clt | awk '{print $1, $2, $3, $4, sin($5*(4*atan2(1,1))/180), $6}' | awk '{print $1, $2, 10*log($6*$5)/log(10), 10*log($3*$5)/log(10), 10*log($4*$5)/log(10)}' >> $name"_CR_RCS_summary.txt"
#echo $site $cr $scr $rcs $inc $avg_clt | awk '{print $1, $2, $3, $4, sin($5*(4*atan2(1,1))/180), $6}' | awk '{print $1, $2, 10*log($6)/log(10), 10*log($3)/log(10), 10*log($4)/log(10)}' >> $name"_CR_RCS_summary.txt"
echo "Site CR_ID Total_Energy Avg_Clutter Total_Clutter Total_Energy_minus_Clutter SCR Phase_Error_metres CR_RCS pwin inc" >> $stub.txt
echo $site $cr $total_E $sum_avg_clt $total_clt $total_E_minus_clt $scr $ph_err $rcs $pwin $inc | awk '{printf "%2g %2g %.10g %.10g %.10g %.10g %.10g %.10g %.10g %2g %.10g\n", $1, $2, 10*log($3)/log(10), 10*log($4)/log(10), 10*log($5)/log(10), 10*log($6)/log(10), 10*log($7)/log(10), $8, 10*log($9)/log(10), $10, 10*log($11)/log(10)}' >> $stub.txt
#echo $site $cr $total_E $sum_avg_clt $total_clt $total_E_minus_clt $scr $rcs | awk '{printf "%2g %2g %.10g %.10g %.10g %.10g %.10g %.10g\n", $1, $2, $3, $4, $5, $6, $7, $8}' >> $name"_CR_RCS_summary.txt"

img_wid=`echo $osf $pwin | awk '{print $1*$2}'`

if [ $flag -eq 0 ]; then
    rasmph $stub.mph $img_wid 1 0 1 1 1 .35 1 $stub.ras $fflag
elif [ $flag -eq 1 ]; then
    raspwr $stub.mph $img_wid 1 0 1 1 1 .35 1 $stub.ras 0
else
    :
fi

plot_cr_response.bash $date $site $cr $img_wid

rm -f rg_data az_data *.mph

#mv -f $date"_"$site*.txt CR/.
#mv -f $date"_"$site.p* CR/.
#mv -f $date"_"$site.ras CR/.
#mv -f $date"_"$site.grd CR/.

rm -f quad.txt

