#! /bin/csh -f


######### example script provided by GAMMA to coregister S1 SLCs. Also uses 'S1_coreg_overlap.csh'. 
# if slave coregistration scripts don't work, or there is burst/swath discontinuities, try running this script on the command line instead.

######### needs rslc_tab file to be created (from 'coregister_S1_slave_SLC.bash' script):

#proc_file=xxxxx
#slave=xxxx
#rlks=10
#alks=2
#polar=VV
#project=`grep Project= $proc_file | cut -d "=" -f 2`
#sensor=`grep Sensor= $proc_file | cut -d "=" -f 2`
#track_dir=`grep Track= $proc_file | cut -d "=" -f 2`
#proj_dir=/g/data1/dg9/INSAR_ANALYSIS/$project/$sensor/GAMMA
#slc_dir=$proj_dir/$track_dir/`grep SLC_dir= $proc_file | cut -d "=" -f 2`
#slave_dir=$slc_dir/$slave
#rslc_tab=$slave_dir/rslc_tab
#slave_slc_name=$slave"_"$polar
#slave_mli_name=$slave"_"$polar"_"$rlks"rlks"
#slc1=r$slave_slc_name"_IW1.slc"
#slc1_par=$slc1.par
#tops_par1=$slc1.TOPS_par
#slc2=r$slave_slc_name"_IW2.slc"
#slc2_par=$slc2.par
#tops_par2=$slc2.TOPS_par
#slc3=r$slave_slc_name"_IW3.slc"
#slc3_par=$slc3.par
#tops_par3=$slc3.TOPS_par
#rslc=$slave_dir/r$slave_slc_name.slc 
#rslc_par=$rslc.par
#rmli=$slave_dir/r$slave_mli_name.mli 
#rmli_par=$rmli.par
#rm -f $rslc_tab
#for swath in 1 2 3; do
#    bslc="slc$swath"
#    bslc_par=${!bslc}.par
#    btops="tops_par$swath"
#    echo $slave_dir/${!bslc} $slave_dir/$bslc_par $slave_dir/${!btops} >> $rslc_tab
#done


######### example command line code:

#S1_coreg_TOPS.csh /g/data1/dg9/INSAR_ANALYSIS/NT_EQ_MAY2016/S1/GAMMA/T075D/SLC/20151017/slc_tab 20151017 /g/data1/dg9/INSAR_ANALYSIS/NT_EQ_MAY2016/S1/GAMMA/T075D/SLC/20160601/slc_tab 20160601 /g/data1/dg9/INSAR_ANALYSIS/NT_EQ_MAY2016/S1/GAMMA/T075D/SLC/20160601/rslc_tab /g/data1/dg9/INSAR_ANALYSIS/NT_EQ_MAY2016/S1/GAMMA/T075D/DEM/20151017_VV_10rlks_rdc.dem 10 2 - - 0.8 0.01 0.8 0 0

#S1_coreg_TOPS.csh /g/data1/dg9/INSAR_ANALYSIS/WA_EQ_MAY2016/S1/GAMMA/T119D/SLC/20151020/slc_tab 20151020 /g/data1/dg9/INSAR_ANALYSIS/WA_EQ_MAY2016/S1/GAMMA/T119D/SLC/20160604/slc_tab 20160604 /g/data1/dg9/INSAR_ANALYSIS/WA_EQ_MAY2016/S1/GAMMA/T119D/SLC/20160604/rslc_tab /g/data1/dg9/INSAR_ANALYSIS/WA_EQ_MAY2016/S1/GAMMA/T119D/DEM/20151020_VV_10rlks_rdc.dem 10 2 - - 0.8 0.01 0.8 0 0


######### once run this script, need to rename SLC and create an MLI, run from command line

#mv *.rslc $rslc
#mv *.rslc_par $rslc_par
#multi_look $rlsc $rslc_par $rmli $rmli_par $rlks $alks




echo "S1_coreg_TOPS: Script to coregister a Sentinel-1 TOPS mode burst SLC to a reference burst SLC v1.1 23-Nov-2015 uw"
echo " "
if ($#argv < 6)then
    echo "usage: S1_coreg_TOPS <SLC1_tab> <SLC1_ID> <SLC2_tab> <SLC2_ID> <RSLC2_tab> [hgt] [RLK] [AZLK] [poly1] [poly2] [cc_thresh] [fraction_thresh] [ph_stdev_thresh] [cleaning] [flag1] [RSLC3_tab]"
    echo "       SLC1_tab    (input) SLC_tab of S1 TOPS burst SLC reference (e.g. 20141015.SLC_tab)"
    echo "       SLC1_ID     (input) ID for reference files (e.g. 20141015)"
    echo "       SLC2_tab    (input) SLC_tab of S1 TOPS burst SLC slave (e.g. 20141027.SLC_tab)"
    echo "       SLC2_ID     (input) ID for slave files (e.g. 20141027)"
    echo "       RSLC2_tab   (input) SLC_tab of co-registered S1 TOPS burst SLC slave (e.g. 20141027.RSLC_tab)"
    echo "       hgt         (input) height map in RDC of MLI-1 mosaic (float, or constant height value; default=0.1)"
    echo "       RLK         number of range looks in the output MLI image (default=10)"
    echo "       AZLK        number of azimuth looks in the output MLI image (default=2)"
    echo "       poly1       polygon file indicating area used for matching (relative to MLI reference to reduce area used for matching)"
    echo "       poly2       polygon file indicating area used for spectral diversity (relative to MLI reference to reduce area used for matching)"
    echo "       cc_thresh   coherence threshold used (default = 0.8)"
    echo "       fraction_thresh   minimum valid fraction of unwrapped phase values used (default = 0.01)"
    echo "       ph_stdev_thresh   phase standard deviation threshold (default = 0.8)"
    echo "       cleaning    flag to indicate if intermediate files are deleted (default = 1 --> deleted,  0: not deleted)"
    echo "       flag1       flag to indicate if existing intermediate files are used (default = 0 --> not used,  1: used)"
    echo "       RSLC3_tab   (input) 3 column list of already available co-registered TOPS slave image to use for overlap interferograms"
    echo "       RSLC3_ID    (input) ID for already available co-registered TOPS slave; if indicated then the differential interferogram between RSLC3 and RSLC2 is calculated"
    echo " "
    exit
endif

# History:
# 14-Jan-2015: checked/updated that SLC and TOPS_par in RSLC2_tab are correctly used
#              the only use of RSLC2_tab is when calling S1_coreg_overlap script 
#              S1_coreg_overlap uses only the burst SLC name in RSLC2_tab but not the burst SLC parameter filename or TOPS_par
#              --> correct even with corrupt TOPS_par in RSLC2_tab
# 14-Jan-2015: changed script to apply matching offset to refine lookup table
# 15-Jan-2015: added generation of a quality file $p.coreg_quality
# 15-Jan-2015: added checking/fixing of zero values in burst 8 parameters of TOPS_par files
# 29-May-2015: added poly2: area to consider for spectral diversity
#  9-Jun-2015:  checking for availability of LAT programs - if not available use entire lookup table (--> slower)
# 19-Jun-2015:  modified to limit maximum number of offset estimation in matching
#  9-Sep-2015:  corrected reading of parameter RSLC3_tab
# 23-Nov-2015:  updated for modifications in offset_pwr_tracking (--> new threshold is 0.2)
# 25-Nov-2015:  added RSLC3_ID option to also calculate differential interferogram between RSLC3 and RSLC2
#  1-Dec-2015:  introduce a maximum number of interations

#########################################################################################


#########################################################################################

if ( "$1" == "$3" ) then
    echo "indicated slc is reference slc --> proceed"
    exit(-1)
endif

if ( "$2" == "$4" ) then
    echo "ERROR: identical ID provided for reference and slave"
    exit(-1)
endif

if ( "$4" == "$5" ) then
    echo "ERROR: SLC_tab files are identical for slave and resampled slave"
    exit(-1)
endif

#defaults for input parameters
set hgt = "0.1"
set RLK = "10"
set AZLK = "2"
set cleaning = "1"   # 1: yes
set itmax = "5"      # maximum number of iterations done

set cc_thresh = "0.8"
set fraction_thresh = "0.01"
set stdev_thresh = "0.8"   # phase offset estimation standard deviation in a burst overlap region in radian

set SLC1_tab = $1
set SLC1_ID = $2
set SLC2_tab = $3
set SLC2_ID = $4
set RSLC2_tab = $5
set RSLC2_ID = $SLC2_ID
set p = "$SLC1_ID""_""$SLC2_ID"
set off = "$SLC1_ID""_""$SLC2_ID"".off"
set doff = "$SLC1_ID""_""$SLC2_ID"".doff"
set flag1 = "0"
set poly1 = "-"
set poly2 = "-"

if ($#argv >= 6) set hgt = $6
if ($#argv >= 7) set RLK = $7
if ($#argv >= 8) set AZLK = $8
if ($#argv >= 9) set poly1 = $9
if ($#argv >= 10) set poly2 = $10
if ($#argv >= 11) set cc_thresh = $11
if ($#argv >= 12) set fraction_thresh = $12
if ($#argv >= 13) set stdev_thresh = $13
if ($#argv >= 14) set cleaning = $14
if ($#argv >= 15) set flag1 = $15
set RSLC3_tab = $SLC1_tab
if ($#argv >= 16) set RSLC3_tab = $16
if ($#argv >= 17) set RSLC3_ID = $17


set SLC = "$SLC2_ID.slc"
set SLC_par = "$SLC2_ID.slc.par"
set MLI = "$SLC2_ID.mli"
set MLI_par = "$SLC2_ID.mli.par" 
set RSLC = "$SLC2_ID.rslc"
set RSLC_par = "$SLC2_ID.rslc.par"
set RMLI = "$SLC2_ID.rmli"
set RMLI_par = "$SLC2_ID.rmli.par"
set REF_SLC = "$SLC1_ID.rslc"
set REF_SLC_par = "$SLC1_ID.rslc.par"
set REF_MLI = "$SLC1_ID.rmli"
set REF_MLI_par = "$SLC1_ID.rmli.par"

echo "test if required input/output files and directories exist"
if (-e "$1" == 0) then 
    echo "ERROR: SLC1_tab file ($1) does not exist"; exit(-1)
endif 
if (-e "$3" == 0) then 
    echo "ERROR: SLC2_tab file ($3) does not exist"; exit(-1)
endif 
if (-e "$5" == 0) then 
    echo "ERROR: RSLC2_tab file ($5) does not exist"; exit(-1)
endif 
if ( ($#argv >= 16) && (-e "$16" == 0 ) ) then 
    echo "ERROR: RSLC3_tab parameter file ($16) does not exist"; exit(-1)
endif 

if ($#argv >= 6) then
  if (-e "$6" == 0) then 
	echo "Height file indicated ($6) does not exist"
	set hgt = $6
	echo "using a constant height value ($6)"
  endif 
else
    echo "using a constant height value ($hgt)"
endif 

if ($#argv >= 9) then
    if ( "$poly1" == "-" )  then 
	echo "no polygon poly1 indicated"
    else
	if (-e "$9" == 0)  then 
	    echo "ERROR: polygon file indicated ($9) does not exist"
	    exit
	endif 
    endif 
endif 


if ($#argv >= 10) then
    if ( "$poly2" == "-" )  then 
	echo "no polygon poly2 indicated"
    else
	if (-e "$10" == 0)  then 
	    echo "ERROR: polygon file indicated ($10) does not exist"
	    exit
	endif 
    endif 
endif 

echo "required input files exist"

#########################################################################################

echo "Sentinel-1 TOPS coregistration quality file" > $p.coreg_quality
echo "###########################################" >> $p.coreg_quality
date >> $p.coreg_quality
echo "" >> $p.coreg_quality
# write out command used and script versions
echo "command used:"  >> $p.coreg_quality
echo "S1_coreg_TOPS $1 $2 $3 $4 $5 $6 $7 $8 $9 $10 $11 $12 $13 $14 $15 $16"  >> $p.coreg_quality
echo "" >> $p.coreg_quality
echo "reference: $SLC1_ID $REF_SLC $REF_SLC_par $SLC1_tab" >> $p.coreg_quality
echo "slave:     $SLC2_ID $SLC $SLC_par $SLC2_tab" >> $p.coreg_quality
echo "coregistered_slave:     $SLC2_ID $RSLC $RSLC_par $RSLC2_tab" >> $p.coreg_quality
echo "reference for spectral diversity refinement:       $RSLC3_tab" >> $p.coreg_quality
echo "polygon used for matching (poly1):            $poly1" >> $p.coreg_quality
echo "polygon used for spectral diversity (poly2):  $poly2" >> $p.coreg_quality

#########################################################################################

if (1) then # (re-) generate SLC and MLI mosaics for reference burst SLC
  # check if it already exists
  if ( (-e "$REF_SLC") && (-e "$REF_SLC_par")  && ("$flag1")  ) then
    echo "using existing SLC mosaic of reference: $REF_SLC $REF_SLC_par"
  else
    echo "SLC_mosaic_S1_TOPS $SLC1_tab $REF_SLC  $REF_SLC_par $RLK $AZLK"
    SLC_mosaic_S1_TOPS $SLC1_tab $REF_SLC  $REF_SLC_par $RLK $AZLK
  endif
  if ( (-e "$REF_MLI") && (-e "$REF_MLI_par")  && ("$flag1") ) then
    echo "using existing MLI mosaic of reference: $REF_MLI $REF_MLI_par"
  else
    multi_look $REF_SLC  $REF_SLC_par $REF_MLI $REF_MLI_par $RLK $AZLK
  endif

  set REF_MLI_width = `awk '$1 == "range_samples:" {print $2}' $REF_MLI_par`      
  set REF_MLI_nlines = `awk '$1 == "azimuth_lines:" {print $2}' $REF_MLI_par`      
  set REF_SLC_width = `awk '$1 == "range_samples:" {print $2}' $REF_SLC_par`      
  set REF_SLC_nlines = `awk '$1 == "azimuth_lines:" {print $2}' $REF_SLC_par`      

  if ( (-e "$REF_MLI.ras")  && ("$flag1")  ) then
    echo "using existing rasterfile of MLI mosaic of reference: $REF_MLI.ras"
  else
    raspwr $REF_MLI $REF_MLI_width
  endif
endif


#########################################################################################

if (1) then # (re-) generate SLC and MLI mosaics for slave burst SLC
  # check if it already exists
  if ( (-e "$SLC") && (-e "$SLC_par")   && ("$flag1") ) then
    echo "using existing SLC mosaic of slave: $SLC, $SLC_par"
  else
    SLC_mosaic_S1_TOPS $SLC2_tab $SLC $SLC_par $RLK $AZLK
  endif
  if ( (-e "$MLI") && (-e "$MLI_par")  && ("$flag1")  ) then
    echo "using existing MLI mosaic of slave: $MLI, $MLI_par"
  else
    multi_look $SLC  $SLC_par $MLI $MLI_par $RLK $AZLK
  endif

  set MLI_width = `awk '$1 == "range_samples:" {print $2}' $MLI_par`      
  set MLI_nlines = `awk '$1 == "azimuth_lines:" {print $2}' $MLI_par`      

  if ( (-e "$MLI.ras")   && ("$flag1") ) then
    echo "using existing rasterfile of MLI mosaic of slave: $MLI.ras"
  else
    raspwr $MLI $MLI_width
  endif
endif

#########################################################################################

if (1) then # determine lookup table based on orbit data and DEM
  if ( (-e "$MLI.lt")  && ("$flag1")  ) then
    echo "using existing lookup table: $MLI.lt"
  else
    echo "rdc_trans $REF_MLI_par $hgt $MLI_par $MLI.lt"
    rdc_trans $REF_MLI_par $hgt $MLI_par $MLI.lt
  endif
endif

if (1) then # masking of lookup table (used for the matching refinement estimation) considering polygon poly1
    if ( (-e "$MLI.lt.masked") && ("$flag1") ) then
	echo "using existing masked lookup table: $MLI.lt.masked"
    else
	ln -s $MLI.lt  $MLI.lt.masked
    endif  
endif    

#########################################################################################

if (1) then # determine starting and ending rows and cols in polygon file
	    # used to speed up the offset estimation

  set r1 = "0"
  set r2 = "$REF_SLC_width"
  set a1 = "0"
  set a2 = "$REF_SLC_nlines"  

endif  

#########################################################################################

if (1) then # reduce offset estimation to 64 x 64 samples max
  set rstep1  = "64"
  set rstep2 = `echo "$r1 $r2" | awk '{printf "%d", ($2-$1)/64}'`
  if ( "$rstep1" > "$rstep2" ) then
    set rstep = "$rstep1"
  else
    set rstep = "$rstep2"
  endif
  
  set azstep1  = "32"
  set azstep2 = `echo "$a1 $a2" | awk '{printf "%d", ($2-$1)/64}'`
  if ( "$azstep1" > "$azstep2" ) then
    set azstep = "$azstep1"
  else
    set azstep = "$azstep2"
  endif

  echo "rstep, azstep: $rstep, $azstep"
endif  

#########################################################################################
#########################################################################################
#########################################################################################

# Iterative improvement of refinement offsets between master SLC and
# resampled slave RSLC  using intensity matching (offset_pwr_tracking)
# Remarks: here only a section of the data is used if a polygon is indicated
# the lookup table is iteratively refined refined with the estimated offsets 
# only a constant offset in range and azimuth (along all burst and swaths) is considered 

echo "" >> $p.coreg_quality
echo "Iterative improvement of refinement offset using matching:" >> $p.coreg_quality

if (1) then # can be used to switch off this refinement (e.g. if it was already done)

if (1) then
  if ( -e "$off" ) then
    rm -f $off
  endif
  create_offset $REF_SLC_par $SLC_par $off 1 $RLK $AZLK 0
endif

set daz10000 = "10000"
set it = "0"
while ( (( "$daz10000" > "100" ) || ( "$daz10000" < "-100" )) && ( "$it" < "$itmax" ) ) 	# iterate while azimuth correction > 0.01 SLC pixel

  # increase iteration counter
  set it = `echo "$it" | awk '{printf "%d", $1+1}'`
  echo "offset refinement using matching iteration $it"
  
  cp $off $off.start

if (1) then
  echo "SLC_interp_lt_S1_TOPS $SLC2_tab $SLC_par $SLC1_tab $REF_SLC_par $MLI.lt.masked $REF_MLI_par $MLI_par $off.start $RSLC2_tab $RSLC $RSLC_par > SLC_interp_lt_S1_TOPS.1.out" 
  SLC_interp_lt_S1_TOPS $SLC2_tab $SLC_par $SLC1_tab $REF_SLC_par $MLI.lt.masked $REF_MLI_par $MLI_par $off.start $RSLC2_tab $RSLC $RSLC_par > SLC_interp_lt_S1_TOPS.1.out 
endif

  if ( -e "$doff" ) then
    rm -f $doff
  endif
  echo "create_offset $REF_SLC_par $SLC_par $doff 1 $RLK $AZLK 0"
  create_offset $REF_SLC_par $SLC_par $doff 1 $RLK $AZLK 0


  # no oversampling as this is not done well because of the doppler ramp
  echo "offset_pwr_tracking $REF_SLC $RSLC $REF_SLC_par $RSLC_par $doff $p.offs $p.snr 128 64 - 1 0.2 $rstep $azstep $r1 $r2 $a1 $a2 4 0 0"
  offset_pwr_tracking $REF_SLC $RSLC $REF_SLC_par $RSLC_par $doff $p.offs $p.snr 128 64 - 1 0.2 $rstep $azstep $r1 $r2 $a1 $a2 4 0 0
  echo "offset_fit $p.offs $p.snr $doff - - 0.2 1 0 >  $p.off.out.$it"
  offset_fit $p.offs $p.snr $doff - - 0.2 1 0 >  $p.off.out.$it
  grep "final model fit std. dev. (samples) range:" $p.off.out.$it > $p.off.out.$it.tmp
  set range_stdev = `awk '$1 == "final" {print $8}' $p.off.out.$it.tmp`
  set azimuth_stdev = `awk '$1 == "final" {print $10}' $p.off.out.$it.tmp`
  rm -f $p.off.out.$it.tmp

  set daz10000 = `awk '$1 == "azimuth_offset_polynomial:" {printf "%d", $2*10000}' $doff`      
  echo "daz10000: $daz10000"
  
  set daz = `awk '$1 == "azimuth_offset_polynomial:" {print $2}' $doff`
  set daz_mli = `echo "$daz" "$AZLK" | awk '{printf "%f", $1/$2}'`
  echo "daz_mli: $daz_mli"
  
  if (1) then    # lookup table refinement
    # determine range and azimuth corrections for lookup table (in mli pixels)
    set dr = `awk '$1 == "range_offset_polynomial:" {print $2}' $doff`      
    set dr_mli = `echo "$dr" "$RLK" | awk '{printf "%f", $1/$2}'`
    set daz = `awk '$1 == "azimuth_offset_polynomial:" {print $2}' $doff`      
    set daz_mli = `echo "$daz" "$AZLK" | awk '{printf "%f", $1/$2}'`
    echo "dr_mli: $dr_mli    daz_mli: $daz_mli"
    echo "dr_mli: $dr_mli    daz_mli: $daz_mli"  > "$p.refinement.iteration.$it"

    if ( -e "$p.diff_par" ) then
      rm -f $p.diff_par
    endif
    create_diff_par $REF_MLI_par $REF_MLI_par $p.diff_par 1 0
    set_value $p.diff_par $p.diff_par "range_offset_polynomial"   "$dr_mli   0.0000e+00   0.0000e+00   0.0000e+00   0.0000e+00   0.0000e+00"
    set_value $p.diff_par $p.diff_par "azimuth_offset_polynomial" "$daz_mli   0.0000e+00   0.0000e+00   0.0000e+00   0.0000e+00   0.0000e+00"
    cp $p.diff_par $p.diff_par.$it

      # update only unmasked lookup table
      mv $MLI.lt $MLI.lt.tmp.$it
      gc_map_fine $MLI.lt.tmp.$it $REF_MLI_width $p.diff_par $MLI.lt 1

  endif  

  echo "matching_iteration_""$it"": $daz $dr    $daz_mli $dr_mli (daz dr   daz_mli dr_mli)" >> $p.coreg_quality
  echo "matching_iteration_stdev_""$it"": $azimuth_stdev $range_stdev (azimuth_stdev range_stdev)" >> $p.coreg_quality
end

endif

#########################################################################################
#########################################################################################
#########################################################################################

# Iterative improvement of azimuth refinement using spectral diversity method   
# Remark: here only a the burst overlap regions within the indicated polygon
# area poly2 are considered

# determine mask for polygon region poly2 that is at the same
# time part of the burst overlap regions

if (1) then
  if ( -e "$SLC1_ID.az_ovr.poly" ) then
    rm -f $SLC1_ID.az_ovr.poly
  endif
    ln -s $MLI.lt $MLI.lt.az_ovr    # use entire area  
endif


#########################################################################################


echo "" >> $p.coreg_quality
echo "Iterative improvement of refinement offset azimuth overlap regions:" >> $p.coreg_quality

set daz10000 = "10000"
set it = "0"
while ( (( "$daz10000" > "5" ) || ( "$daz10000" < "-5" )) && ( "$it" < "$itmax" ) ) 	# iterate while azimuth correction >= 0.0005 SLC pixel

  # increase iteration counter
  set it = `echo "$it" | awk '{printf "%d", $1+1}'`
  echo "offset refinement using spectral diversity in azimuth overlap region iteration $it"
  
  cp $off $off.start

  echo "SLC_interp_lt_S1_TOPS $SLC2_tab $SLC_par $SLC1_tab $REF_SLC_par $MLI.lt.az_ovr $REF_MLI_par $MLI_par $off.start $RSLC2_tab $RSLC $RSLC_par"
  SLC_interp_lt_S1_TOPS $SLC2_tab $SLC_par $SLC1_tab $REF_SLC_par $MLI.lt.az_ovr $REF_MLI_par $MLI_par $off.start $RSLC2_tab $RSLC $RSLC_par > SLC_interp_lt_S1_TOPS.2.out

if ( ($#argv >= 16) && (-e "$16" ) ) then 
  echo "S1_coreg_overlap.csh $SLC1_tab $RSLC2_tab $p $off.start $off $cc_thresh $fraction_thresh $stdev_thresh $cleaning $RSLC3_tab > $off.az_ovr.$it.out"
  S1_coreg_overlap.csh $SLC1_tab $RSLC2_tab $p $off.start $off $cc_thresh $fraction_thresh $stdev_thresh $cleaning $RSLC3_tab > $off.az_ovr.$it.out
else
  echo "S1_coreg_overlap.csh $SLC1_tab $RSLC2_tab $p $off.start $off $cc_thresh $fraction_thresh $stdev_thresh $cleaning > $off.az_ovr.$it.out"
  S1_coreg_overlap.csh $SLC1_tab $RSLC2_tab $p $off.start $off $cc_thresh $fraction_thresh $stdev_thresh  $cleaning > $off.az_ovr.$it.out
endif

  set daz = `awk '$1 == "azimuth_pixel_offset" {print $2}' $off.az_ovr.$it.out`      
  set daz10000 = `awk '$1 == "azimuth_pixel_offset" {printf "%d", $2*10000}' $off.az_ovr.$it.out`      
  echo "daz10000: $daz10000"
  cp $off $off.az_ovr.$it

  echo "az_ovr_iteration_""$it"": $daz (daz in SLC pixel)" >> $p.coreg_quality
  more $p.results >>  $p.coreg_quality
  echo "" >> $p.coreg_quality

end

#########################################################################################
#########################################################################################
#########################################################################################

# resample full data set
if (1) then
  echo "SLC_interp_lt_S1_TOPS $SLC2_tab $SLC_par $SLC1_tab $REF_SLC_par $MLI.lt $REF_MLI_par $MLI_par $off $RSLC2_tab $RSLC $RSLC_par > SLC_interp_lt_S1_TOPS.3.out"
  SLC_interp_lt_S1_TOPS $SLC2_tab $SLC_par $SLC1_tab $REF_SLC_par $MLI.lt $REF_MLI_par $MLI_par $off $RSLC2_tab $RSLC $RSLC_par > SLC_interp_lt_S1_TOPS.3.out 
endif

##############################################################

# generate differential interferogram (also for testing for jumps at burst overlaps)

if (1) then
  # topographic phase simulation 
  if ( (-e "$p.sim_unw")   && ("$flag1") ) then
    echo "using existing simulated phase: $p.sim_unw"
  else
    echo "phase_sim_orb $REF_SLC_par $SLC_par $off $hgt $p.sim_unw $REF_SLC_par - - 1 1"
    phase_sim_orb $REF_SLC_par $SLC_par $off $hgt $p.sim_unw $REF_SLC_par - - 1 1
  endif
  
  # calculation of a S1 TOPS differential interferogram
  echo "SLC_diff_intf $REF_SLC $RSLC $REF_SLC_par $RSLC_par $off $p.sim_unw $p.diff $RLK $AZLK 1 0 0.2 1 1"
  SLC_diff_intf $REF_SLC $RSLC $REF_SLC_par $RSLC_par $off $p.sim_unw $p.diff $RLK $AZLK 1 0 0.2 1 1
  rasmph_pwr24 $p.diff $REF_MLI $REF_MLI_width 1 1 0 1 1 1. .35 1 $p.diff.ras

  echo ""  >> $p.coreg_quality
  echo "Generated differential interferogram $p.diff"  >> $p.coreg_quality
  echo "to display use:   eog $p.diff.ras &"  >> $p.coreg_quality

endif


if ( ($#argv >= 16) && (-e "$16" ) && ($#argv >= 17) ) then    # generate the differential interferogram with the $RSLC3_ID.rslcscene
  echo "SLC_mosaic_S1_TOPS $RSLC3_tab $RSLC3_ID.rslc  $RSLC3_ID.rslc.par $RLK $AZLK 0 $SLC1_tab"
  SLC_mosaic_S1_TOPS $RSLC3_tab $RSLC3_ID.rslc $RSLC3_ID.rslc.par $RLK $AZLK 0 $SLC1_tab
  echo "multi_look $RSLC3_ID.rslc $RSLC3_ID.rslc.par RMLI3 MLI3_par $RLK $AZLK"
  multi_look $RSLC3_ID.rslc $RSLC3_ID.rslc.par RMLI3 MLI3_par $RLK $AZLK

  # topographic phase simulation 
  set q = "$RSLC3_ID""_""$SLC2_ID"
  echo "phase_sim_orb $RSLC3_ID.rslc.par $SLC_par $off $hgt $q.sim_unw $REF_SLC_par - - 1 1"
  phase_sim_orb $RSLC3_ID.rslc.par $SLC_par $off $hgt $q.sim_unw $REF_SLC_par - - 1 1
  
  # calculation of a S1 TOPS differential interferogram
  echo "SLC_diff_intf $RSLC3_ID.rslc $RSLC $RSLC3_ID.rslc.par $RSLC_par $off $q.sim_unw $q.diff $RLK $AZLK 1 0 0.2 1 1"
  SLC_diff_intf $RSLC3_ID.rslc $RSLC $RSLC3_ID.rslc.par $RSLC_par $off $q.sim_unw $q.diff $RLK $AZLK 1 0 0.2 1 1
  rasmph_pwr24 $q.diff RMLI3 $REF_MLI_width 1 1 0 1 1 1. .35 1 $q.diff.ras

  echo ""  >> $p.coreg_quality
  echo "Generated differential interferogram $q.diff"  >> $p.coreg_quality
  echo "to display use:   eog $q.diff.ras &"  >> $p.coreg_quality

endif


#######################################3

# cleaning

if ( "$cleaning" ) then
  rm -f $MLI.lt.masked
  rm -f $MLI.lt.masked.tmp.?
  rm -f $MLI.lt.tmp.?
  rm -f $MLI.lt.az_ovr   
  rm -f $doff
  rm -f $off.?
  rm -f $off.az_ovr.?
  rm -f $off.out.?
  rm -f $off.start 
endif

echo ""  >> $p.coreg_quality
echo "end of S1_coreg_TOPS"  >> $p.coreg_quality
date >> $p.coreg_quality

#######################################3


exit
