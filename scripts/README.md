Running the extraction pipeline
===============================

This README describes how to process one night's worth of spectroscopic data.
The input files are expected to be 2D raw CCD frames from the output of the
telescope instrument software. The output files are a set of FITS files
containing 1D extracted, wavelength-calibrated spectra for each source file.

Processing the raw CCD frames
-----------------------------

The first step is to bias-correct, flat-correct, and trim the raw frames. Some
exposures may be known to be bad -- you can specify filenames to skip by
creating a text file with one filename per line (in this case,
``skip_files.txt``):

```bash
python extract_1d.py -p ../data/mdm-spring-2017/n1 \
--skiplist=../data/mdm-spring-2017/n1/skip_files.txt -v
```

The above example will process all files in the path
``../data/mdm-spring-2017/n1``, skipping any file listed in
``../data/mdm-spring-2017/n1/skip_files.txt``. The processed 2D frame files will
be output to the path ``../data/mdm-spring-2017/n1_proc`` (for processed)
starting with the name ``proc_*``. The 1D extracted spectra (not wavelength
calibrated) will also be in this directory with filenames that start
``1d_proc_*``.

Initializing the wavelength solution
------------------------------------

The next step is to interactively identify emission lines in a comparison lamp
spectrum. To do that, you'll need to either specify the path to a processed
HgNe+Ne arc lamp frame, or to a directory containing one (and the first one
found will be used). You also need to specify a path to a text file containing
known lines that should be auto-identified in the spectrum once enough lines
have been found. For an HgNe+Ne lamp and for a wavelength range ~3600-7200
Angstroms, this file is provided in ``comoving_rv/longslit/arc/hgne.txt``. For
example:

```bash
python init_wavelength.py -p ../data/mdm-spring-2017/n1_proc/proc_n1.0137.fit \
--linelist=../comoving_rv/longslit/arc/hgne.txt -v
```

If you've already run the interactive script and have an initial guess for the
auto-identification of the lines, you can specify a CSV file containing two
columns (pixel and wavelength):

```bash
python init_wavelength.py -p ../data/mdm-spring-2017/n1_proc/proc_n1.0137.fit \
--linelist=../comoving_rv/longslit/arc/hgne.txt \
--init-file=../data/mdm-spring-2017/n1_proc/init_wavelength.csv -v
```

The residuals should all be <~0.02 Angstroms.

This outputs a pixel-to-wavelength map file in the same processed directory
(in this case, ``../data/mdm-spring-2017/n1_proc/``) called
``master_wavelength.csv``.

Full wavelength calibration
---------------------------

The last step in the reduction process is to add wavelength values to the 1D
extracted spectrum files (i.e. map the pixel values to wavelength values and add
a column). This is done in two steps. For the first step, a polynomial function
is fit to the