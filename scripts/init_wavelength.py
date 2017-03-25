"""
Generate a rough, initial wavelength solution for a 1D spectrum.

TODO:
- Make wavelength button better (icon and make sure it doesn't stay pressed)

"""

# Standard library
from os import path
import logging

# Third-party
import ccdproc
from ccdproc import CCDData
from matplotlib.widgets import SpanSelector
import matplotlib.pyplot as plt
import numpy as np
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from scipy.interpolate import InterpolatedUnivariateSpline

# Package
from comoving_rv.longslit import voigt_polynomial
from comoving_rv.longslit.wavelength import fit_emission_line

logger = logging.getLogger('init_wavelength')
formatter = logging.Formatter('%(levelname)s:%(name)s:  %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.propagate = False

class GUIWavelengthSolver(object):

    def __init__(self, pix, flux, flux_ivar=None, line_list=None, init_map=None):

        # the spectrum data
        self.pix = pix
        self.flux = flux
        self.flux_ivar = flux_ivar

        if line_list is not None:
            self.line_list = np.array(line_list)
        else:
            self.line_list = None

        # make the plot
        fig,ax = plt.subplots(1, 1)
        ax.plot(pix, flux, marker='', drawstyle='steps-mid')
        ax.set_xlim(pix.min(), pix.max())

        # since we require QT anyways...
        figManager = plt.get_current_fig_manager()
        figManager.window.showMaximized()

        self.fig = fig
        self.ax = ax

        # for caching
        self._map_dict = dict()

        if init_map is None:
            self._map_dict['wavel'] = []
            self._map_dict['pixel'] = []

        else:
            self._map_dict['wavel'] = init_map['wavelength']
            self._map_dict['pixel'] = init_map['pixel']

        self._line_std_G = None
        self._line_fwhm_L = None
        self._done_wavel_idx = []

        # HACK: magic numbers, initial line widths
        self._line_std_G = 0.6
        self._line_fwhm_L = 0.1

        # for storing UI elements
        self._ui = dict()

        self._setup_ui()

    def _setup_ui(self):
        # Add a side menu for specifying the wavelength of the selected line
        panel = QtWidgets.QWidget()

        label = QtWidgets.QLabel("Enter wavelength [Å]:", panel)
        help_label = QtWidgets.QLabel("Enter a wavelength value, zoom in, then select the region "
                                      "containing the emission line at the specified wavelength.",
                                      panel)
        help_label.setStyleSheet("font-style: italic;")
        self._ui['textbox'] = QtWidgets.QLineEdit(parent=panel)

        panel.layout = QtWidgets.QGridLayout(panel)
        panel.layout.addWidget(label, 0, 0, 1, 1)
        panel.layout.addWidget(self._ui['textbox'], 0, 1, 1, 1)
        panel.layout.addWidget(help_label, 1, 0, 1, 2, Qt.AlignCenter)

        main_window = self.fig.canvas.manager.window
        dock = QtWidgets.QDockWidget("Enter wavelength:", main_window)
        main_window.addDockWidget(Qt.BottomDockWidgetArea, dock)
        dock.setWidget(panel)

        # A 1D span selector to highlight a given line
        span = SpanSelector(self.ax, self._on_select, 'horizontal', useblit=True,
                            rectprops=dict(alpha=0.5, facecolor='red'))
        span.set_active(False)

        def enable_span():
            tb = self.fig.canvas.manager.toolbar

            if span.active:
                span.set_active(False)
            else:
                span.set_active(True)

            if tb._active == 'PAN':
                tb.pan()
                tb._actions['pan'].setChecked(False)

            if tb._active == 'ZOOM':
                tb.zoom()
                tb._actions['zoom'].setChecked(False)

        span_control = QtWidgets.QPushButton('λ')
        span_control.setCheckable(True)
        span_control.clicked.connect(enable_span)
        span_control.setStyleSheet("color: #de2d26; font-weight: bold;")
        self.fig.canvas.manager.toolbar.addWidget(span_control)

        # setup auto-identify button
        if self.line_list is not None:
            autoid_control = QtWidgets.QPushButton('auto-identify')
            autoid_control.clicked.connect(self.auto_identify)
            self.fig.canvas.manager.toolbar.addWidget(autoid_control)

        # add a button for "done"
        done_control = QtWidgets.QPushButton('done')
        done_control.clicked.connect(self._finish)
        self.fig.canvas.manager.toolbar.addWidget(done_control)

        plt.show()

    def _on_select(self, xmin, xmax):
        wvln = self._ui['textbox'].text().strip()

        if wvln == '':
            self._ui['textbox'].setText('Error: please enter a wavelength value before selecting')
            return

        wave_val = float(wvln)

        # if line_list specified, find closest line from list:
        if self.line_list is not None:
            absdiff = np.abs(self.line_list - wave_val)
            idx = absdiff.argmin()
            if absdiff[idx] > 1.:
                logger.error("Couldn't find precise line corresponding to "
                             "input {:.3f}".format(wave_val))
                return

            logger.info("Snapping input wavelength {:.3f} to line list "
                        "value {:.3f}".format(wave_val, self.line_list[idx]))
            wave_val = self.line_list[idx]
            self._done_wavel_idx.append(idx)

        line_props = self.get_line_props(xmin, xmax)
        if line_props is None:
            return

        self.draw_line_marker(line_props, wave_val, xmin, xmax)

        self.fig.suptitle('')
        plt.draw()
        self.fig.canvas.draw()

        self._map_dict['wavel'].append(wave_val)
        self._map_dict['pixel'].append(line_props['x_0'])

        print(self._map_dict['wavel'])
        print(self._map_dict['pixel'])

    def get_line_props(self, xmin, xmax, **kwargs):
        i1 = int(np.floor(xmin))
        i2 = int(np.ceil(xmax))+1

        pix = self.pix[i1:i2]
        flux = self.flux[i1:i2]

        if self.flux_ivar is not None:
            flux_ivar = self.flux_ivar[i1:i2]
        else:
            flux_ivar = None

        try:
            line_props = fit_emission_line(pix, flux, flux_ivar, n_bg_coef=2, **kwargs)
        except Exception as e:
            raise
            msg = "Failed to fit line!"
            logger.error(msg)
            logger.error(str(e))
            self._ui['textbox'].setText("ERROR: See terminal for more information.")
            return None

        # store these to help auto-identify
        self._line_std_G = line_props['std_G']
        self._line_fwhm_L = line_props['fwhm_L']

        return line_props

    def draw_line_marker(self, line_props, wavelength, xmin, xmax):
        pix_grid = np.linspace(xmin, xmax, 512)
        flux_grid = voigt_polynomial(pix_grid, **line_props)

        peak = flux_grid.max()
        x0 = line_props['x_0']

        space = 0.05*peak
        self.ax.plot([x0,x0], [peak+space,peak+3*space],
                     lw=1., linestyle='-', marker='', alpha=0.5, c='#2166AC')
        self.ax.plot(pix_grid, flux_grid, zorder=100,
                     lw=1., linestyle='-', marker='', alpha=1., c='#31a354')
        self.ax.text(x0, peak+4*space, "{:.3f} $\AA$".format(wavelength),
                     ha='center', va='bottom', rotation='vertical')

    def auto_identify(self):
        if self.line_list is None:
            raise ValueError("Can't auto-identify lines without a line list.")

        _idx = np.argsort(self._map_dict['wavel'])
        wvln = np.array(self._map_dict['wavel'])[_idx]
        pixl = np.array(self._map_dict['pixel'])[_idx]

        # build an approximate wavelength solution to predict where lines are
        spl = InterpolatedUnivariateSpline(wvln, pixl, k=3)

        predicted_pixels = spl(self.line_list)

        new_wavels = []
        new_pixels = []

        # from Wikipedia: https://en.wikipedia.org/wiki/Voigt_profile
        fG = 2*self._line_std_G*np.sqrt(2*np.log(2))
        fL = self._line_fwhm_L
        lw = 0.5346*fL + np.sqrt(0.2166*fL**2 + fG**2)
        for pix_ctr,xmin,xmax,wave_idx,wave in zip(predicted_pixels,
                                                   predicted_pixels-3*lw,
                                                   predicted_pixels+3*lw,
                                                   range(len(self.line_list)),
                                                   self.line_list):

            if pix_ctr < 200 or pix_ctr > 1600: # skip if outside good rows
                continue

            elif wave_idx in self._done_wavel_idx: # skip if already fit
                continue

            logger.debug("Fitting line at predicted pix={:.2f}, λ={:.2f}"
                         .format(pix_ctr, wave))
            try:
                lp = self.get_line_props(xmin, xmax,
                                         std_G0=self._line_std_G,
                                         fwhm_L0=self._line_fwhm_L)
            except Exception as e:
                logger.error("Failed to auto-fit line at {} ({msg})"
                             .format(wave, msg=str(e)))
                continue

            if lp is None or lp['amp'] < 100.: # HACK
                continue

            # figure out closest line
            # _all_pix = np.concatenate((self._map_dict['pixel'], new_pixels))
            # _all_wav = np.concatenate((self._map_dict['wavel'], new_wavels))
            # _diff = np.abs(lp['x_0'] - np.array(_all_pix))
            # min_diff_idx = np.argmin(_diff)
            # min_diff_pix = _all_pix[min_diff_idx]
            # min_diff_wav = _all_wav[min_diff_idx]

            # if _diff[min_diff_idx] < 3.:
            #     logger.error("Fit line is too close to another at pix={:.2f}, λ={:.2f}"
            #                  .format(min_diff_pix, min_diff_wav))
            #     continue

            self.draw_line_marker(lp, wave, xmin, xmax)
            new_wavels.append(wave)
            new_pixels.append(pix_ctr)
            self._done_wavel_idx.append(wave_idx)

        self.fig.canvas.draw()

        _idx = np.argsort(new_wavels)
        self._map_dict['wavel'] = np.array(new_wavels)[_idx]
        self._map_dict['pixel'] = np.array(new_pixels)[_idx]

    def _finish(self):
        self.solution = dict()
        self.solution['wavelength'] = self._map_dict['wavel']
        self.solution['pixel'] = self._map_dict['pixel']
        plt.close(self.fig)

def main(proc_path, linelist_file, init_file=None, overwrite=False):
    """ """

    proc_path = path.realpath(path.expanduser(proc_path))
    if not path.exists(proc_path):
        raise IOError("Path '{}' doesn't exist".format(proc_path))
    logger.info("Reading data from path: {}".format(proc_path))

    # read linelist if specified
    if linelist_file is not None:
        line_list = np.genfromtxt(linelist_file, usecols=[0], dtype=float)

    else:
        line_list = None

    if path.isdir(proc_path):
        wavelength_data_file = None
        output_path = proc_path

    elif path.isfile(proc_path):
        wavelength_data_file = proc_path
        base_path, name = path.split(proc_path)
        output_path = base_path

    else:
        raise RuntimeError("how?!")

    logger.info("Saving processed files to path: {}".format(output_path))

    if wavelength_data_file is None: # find a COMP lamp:
        ic = ccdproc.ImageFileCollection(proc_path)

        hdu = None
        for hdu,wavelength_data_file in ic.hdus(return_fname=True, imagetyp='COMP'):
            break
        else:
            raise IOError("No COMP lamp file found in {}".format(proc_path))

        wavelength_data_file = path.join(ic.location, wavelength_data_file)

    logger.info("Using file: {}".format(wavelength_data_file))

    if init_file is not None:
        logger.info("Using initial guess at pixel-to-wavelength mapping from "
                    "initialization file: {}".format(init_file))

        d = np.genfromtxt(init_file, names=True, delimiter=',')

        init_map = dict()
        init_map['pixel'] = d['pixel']
        init_map['wavelength'] = d['wavelength']

    else:
        init_map = None

    # read 2D CCD data
    ccd = CCDData.read(wavelength_data_file)

    # create 1D pixel and flux grids
    col_pix = np.arange(ccd.shape[0])

    # HACK: this is a total hack, but seems to be ok for the comp lamp spectra we have
    flux = np.mean(ccd.data[:,100:200], axis=1)
    flux_ivar = np.sum(1/ccd.uncertainty[:,100:200].array**2, axis=1)
    flux_ivar[np.isnan(flux_ivar)] = 0.

    gui = GUIWavelengthSolver(col_pix, flux, flux_ivar=flux_ivar,
                              line_list=line_list, init_map=init_map)

    wav = gui.solution['wavelength']
    pix = gui.solution['pixel']

    # write the pixel-wavelength nodes out to file
    with open(path.join(output_path, 'master_wavelength.csv'), 'w') as f:
        txt = ["# pixel, wavelength"]
        for row in zip(pix, wav):
            txt.append("{:.5f},{:.5f}".format(*row))
        f.write("\n".join(txt))

    # TODO:
    fig2,axes2 = plt.subplots(2,1,figsize=(6,10))
    axes2[0].plot(pix, wav, linestyle='none', marker='o')

    coef = np.polynomial.polynomial.polyfit(pix, wav, deg=9) # MAGIC NUMBER
    pred = np.polynomial.polynomial.polyval(pix, coef)
    axes2[1].plot(pix, wav-pred,
                  linestyle='none', marker='o')
    plt.show()

if __name__ == "__main__":
    from argparse import ArgumentParser
    import logging

    # Define parser object
    parser = ArgumentParser(description="")

    vq_group = parser.add_mutually_exclusive_group()
    vq_group.add_argument('-v', '--verbose', action='count', default=0, dest='verbosity')
    vq_group.add_argument('-q', '--quiet', action='count', default=0, dest='quietness')

    parser.add_argument('-o', '--overwrite', action='store_true', dest='overwrite',
                        default=False, help='Destroy everything.')

    parser.add_argument('-p', '--path', dest='proc_path', required=True,
                        help='Path to a PROCESSED night or chunk of data to process. Or, '
                             'path to a specific comp file.')
    parser.add_argument('--linelist', dest='linelist_file', type=str, default=None,
                        help='Path to a text file where the 0th column is a list of '
                             'emission lines for the comparison lamp. Default is to '
                             'require the user to enter exact wavelengths.')
    parser.add_argument('--init-file', dest='init_file', type=str, default=None,
                        help='Path to a CSV file where the 0th column is a list of '
                             'pixel values and the 1st column is a list of wavelength '
                             'values to initialize the auto-solution.')

    args = parser.parse_args()

    # Set logger level based on verbose flags
    if args.verbosity != 0:
        if args.verbosity == 1:
            logger.setLevel(logging.DEBUG)
        else: # anything >= 2
            logger.setLevel(1)

    elif args.quietness != 0:
        if args.quietness == 1:
            logger.setLevel(logging.WARNING)
        else: # anything >= 2
            logger.setLevel(logging.ERROR)

    else: # default
        logger.setLevel(logging.INFO)

    kwargs = vars(args)
    kwargs.pop('verbosity')
    kwargs.pop('quietness')
    main(**kwargs)